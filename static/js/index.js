const { createApp } = Vue;
const PROMPT_TEXT_NOT_GENERATED = '尚未生成 Prompt';
const PROMPT_TEXT_GENERATING = '生成中...';
const PROMPT_TEXT_NOT_RETURNED = '未返回 prompt';
const CONTEXT_WARN_RATIO = 0.80;
const CONTEXT_DANGER_RATIO = 0.92;
const CONTEXT_NOTICE_COOLDOWN_MS = 12000;
const AUTO_COMPRESS_KEEP_RECENT = 8;
const AUTO_COMPRESS_TRIGGER_RATIO = CONTEXT_WARN_RATIO;
const AUTO_COMPRESS_SUMMARY_MAX_CHARS = 1400;
const AUTO_COMPRESS_MIN_EXCESS_MESSAGES = 2;
const AUTO_COMPRESS_MIN_TOTAL_MESSAGES = AUTO_COMPRESS_KEEP_RECENT + AUTO_COMPRESS_MIN_EXCESS_MESSAGES;
const AUTO_COMPRESS_SUMMARY_PREFIX = '以下为早期多轮对话压缩摘要，请基于该摘要与后续消息保持回答连续性：';

createApp({
  delimiters: ['[[', ']]'],

  data() {
    return {
      reportType: 'stat',
      reportStyle: 'simple',
      metric: 'sales_amount',
      granularity: 'month',
      startDate: '',
      endDate: '',
      topN: 10,
      selectedDimensions: ['total'],
      showReasoning: true,

      dimensionOptions: [
        { value: 'total',    label: '总量' },
        { value: 'genre',    label: '流派' },
        { value: 'artist',   label: '艺术家' },
        { value: 'country',  label: '国家' },
        { value: 'city',     label: '城市' },
        { value: 'customer', label: '客户' },
        { value: 'employee', label: '员工' },
      ],

      displayMessages: [],
      llmMessages: [],
      chatInput: '',
      sending: false,
      nextMsgId: 1,

      cumulativeChars: 0,
      cumulativeTokens: 0,
      contextLimitTokens: 128000,
      contextLevel: 'ok',
      contextMessage: '上下文充足。',
      lastCtxCheckAt: 0,
      ctxCheckTimer: null,
      lastCtxNoticeAt: 0,

      promptText: PROMPT_TEXT_NOT_GENERATED,
      plots: [],
      hasPendingGeneratedPrompt: false,

      exportTemplates: [],
      userTemplateIds: [],
      selectedTemplateId: '',
      exportTitle: '',
      exporting: false,

      useCustomTpl: false,
      tplId: 'my_custom_tpl',
      tplName: '用户自定义模板',
      tplBodyFont: '宋体',
      tplBodySize: 11,
      tplH1Font: '微软雅黑',
      tplH1Size: 15,
      tplLineSpacing: 1.5,
      tplIndentChars: 2,
      tplMTop: 2.5,
      tplMRight: 2.2,
      tplMBottom: 2.5,
      tplMLeft: 2.2,

      showModal: false,
      modalLoading: false,
      modalQueries: [],
      modalError: '',

      isResizing: false,
      chatWidth: null,
    };
  },

  computed: {
    chatColStyle() {
      if (this.chatWidth !== null) {
        return { flex: '0 0 ' + this.chatWidth + 'px' };
      }
      return { flex: '1' };
    },
    contextUsageRatio() {
      const limit = Number(this.contextLimitTokens || 0);
      if (!limit) return 0;
      return Number(this.cumulativeTokens || 0) / limit;
    },
    contextUsagePercent() {
      return (this.contextUsageRatio * 100).toFixed(1) + '%';
    },
    ctxBadgeClass() {
      if (this.contextLevel === 'danger') return 'ctx-badge ctx-danger';
      if (this.contextLevel === 'warn') return 'ctx-badge ctx-warn';
      return 'ctx-badge ctx-ok';
    },
    ctxBadgeText() {
      if (this.contextLevel === 'danger') return '高风险';
      if (this.contextLevel === 'warn') return '预警';
      return '正常';
    },
    showDeleteTplBtn() {
      return this.userTemplateIds.includes(this.selectedTemplateId);
    },
  },

  async mounted() {
    if (window.marked && typeof window.marked.setOptions === 'function') {
      window.marked.setOptions({ breaks: true, gfm: true });
    }

    this.displayMessages.push({
      id: this.nextMsgId++,
      role: 'system',
      kind: 'notice',
      rawContent:
        '👋 欢迎使用 Chinook 报告对话工作台\n\n' +
        '**使用步骤：**\n' +
        '1️⃣ 左侧配置报告参数\n' +
        '2️⃣ 点击"生成Prompt与图像"\n' +
        '3️⃣ 点击"开始报告生成"\n' +
        '4️⃣ 可继续追问，实现多轮对话',
    });

    await this.loadExportTemplates();
    await this.refreshCtxThrottled(true);

    window.addEventListener('focus', () => this.loadExportTemplates());
    window.addEventListener('storage', (e) => {
      if (e.key === 'tpl_saved') this.loadExportTemplates();
    });
    try {
      this._tplBC = new BroadcastChannel('tpl_saved');
      this._tplBC.onmessage = () => this.loadExportTemplates();
    } catch (e) {
      console.warn('BroadcastChannel unavailable:', e);
    }

    document.addEventListener('mousemove', this.onMouseMove);
    document.addEventListener('mouseup', this.onMouseUp);
    document.addEventListener('keydown', this.onKeyDown);
  },

  beforeUnmount() {
    document.removeEventListener('mousemove', this.onMouseMove);
    document.removeEventListener('mouseup', this.onMouseUp);
    document.removeEventListener('keydown', this.onKeyDown);
  },

  methods: {
    pushSystemNotice(text) {
      this.displayMessages.push({
        id: this.nextMsgId++,
        role: 'system',
        kind: 'notice',
        rawContent: text,
      });
      this.scrollChatToBottom();
    },

    applyContextStatus(payload, options) {
      const cfg = options || {};
      const shouldNotify = Boolean(cfg.notifyUser);
      const now = Date.now();
      const data = payload || {};

      this.cumulativeChars = Number(data.cumulative_chars_est || 0);
      this.cumulativeTokens = Number(data.cumulative_tokens_est || data.used_tokens_est || 0);
      this.contextLimitTokens = Number(data.limit_tokens_est || 128000);

      let level = String(data.level || '').trim();
      if (!level) {
        const ratio = this.contextUsageRatio;
        if (ratio >= CONTEXT_DANGER_RATIO) level = 'danger';
        else if (ratio >= CONTEXT_WARN_RATIO) level = 'warn';
        else level = 'ok';
      }
      this.contextLevel = level;
      this.contextMessage = String(data.message || '').trim()
        || (level === 'danger'
          ? '上下文接近极限，建议立即开启历史压缩或新建会话。'
          : (level === 'warn' ? '上下文已较高，建议精简历史消息。' : '上下文充足。'));

      if (!shouldNotify || level === 'ok') return;
      if (now - this.lastCtxNoticeAt < CONTEXT_NOTICE_COOLDOWN_MS) return;
      this.lastCtxNoticeAt = now;
      this.pushSystemNotice('⚠️ ' + this.contextMessage);
    },

    shortenForSummary(text, maxLen) {
      const clean = String(text || '').replace(/\s+/g, ' ').trim();
      if (!clean) return '';
      const limit = Number(maxLen || 120);
      if (clean.length <= limit) return clean;
      return clean.slice(0, limit) + '…';
    },

    buildHistorySummary(historyMessages, maxChars) {
      const lines = [];
      const limit = Number(maxChars || AUTO_COMPRESS_SUMMARY_MAX_CHARS);
      let used = 0;
      for (const msg of historyMessages || []) {
        const roleName = (msg && msg.role) || '';
        const role = roleName === 'user' ? '用户' : (roleName === 'system' ? '系统' : '助手');
        const content = this.shortenForSummary((msg && msg.content) || '', 120);
        if (!content) continue;
        const line = `- ${role}：${content}`;
        if ((used + line.length) > limit) break;
        lines.push(line);
        used += line.length;
      }
      if (!lines.length) return '';
      return AUTO_COMPRESS_SUMMARY_PREFIX + '\n' + lines.join('\n');
    },

    async autoCompressHistoryIfNeeded() {
      if (this.contextUsageRatio < AUTO_COMPRESS_TRIGGER_RATIO) return false;
      if (!Array.isArray(this.llmMessages)) return false;
      const preservedSystemMessages = this.llmMessages.filter(m => {
        const content = String((m && m.content) || '');
        return (m && m.role) === 'system' && !content.startsWith(AUTO_COMPRESS_SUMMARY_PREFIX);
      });
      const conversationMessages = this.llmMessages.filter(m => (m && m.role) !== 'system');
      if (conversationMessages.length <= AUTO_COMPRESS_MIN_TOTAL_MESSAGES) return false;

      const keepRecent = conversationMessages.slice(-AUTO_COMPRESS_KEEP_RECENT);
      const toCompress = conversationMessages.slice(0, -AUTO_COMPRESS_KEEP_RECENT);
      const summary = this.buildHistorySummary(toCompress, AUTO_COMPRESS_SUMMARY_MAX_CHARS);
      if (!summary) return false;

      this.llmMessages = [...preservedSystemMessages, { role: 'system', content: summary }, ...keepRecent];
      this.pushSystemNotice(`⚠️ 上下文较长，已自动压缩 ${toCompress.length} 条历史消息，并保留最近 ${AUTO_COMPRESS_KEEP_RECENT} 条。`);
      await this.refreshCtxThrottled(true);
      return true;
    },

    escapeHtml(s) {
      return String(s || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
    },

    renderMarkdown(text) {
      try {
        if (window.marked && typeof window.marked.parse === 'function') {
          return window.marked.parse(text || '');
        }
        return '<p>' + this.escapeHtml(text || '') + '</p>';
      } catch (e) {
        return '<p>' + this.escapeHtml(text || '') + '</p>';
      }
    },

    fmtVal(v) {
      if (v === null || v === undefined) return '';
      if (typeof v === 'number') return Number.isInteger(v) ? String(v) : v.toFixed(2);
      return String(v);
    },

    slugifyKey(text) {
      if (!text) return 'chart';
      return text
        .replace(/[^a-zA-Z0-9\u4e00-\u9fa5]+/g, '_')
        .replace(/^_+|_+$/g, '')
        .toLowerCase()
        .slice(0, 64);
    },

    buildPlotImages(plots) {
      const map = {};
      (plots || []).forEach(p => {
        const key = this.slugifyKey(p.title);
        if (p.image) map[key] = p.image;
      });
      return map;
    },

    buildPlotImagesMeta(plots) {
      const map = {};
      (plots || []).forEach(p => {
        const key = this.slugifyKey(p.title);
        if (p.image && p.meta) map[key] = p.meta;
      });
      return map;
    },

    // ---- Message helpers ----
    getMsgClass(msg) {
      if (msg.kind === 'notice') return 'msg msg-notice';
      if (msg.role === 'user') return 'msg msg-user';
      if (msg.kind === 'reasoning') return 'msg msg-reasoning';
      return 'msg msg-assistant';
    },

    getMsgRoleLabel(msg) {
      if (msg.role === 'user') return '用户';
      if (msg.kind === 'reasoning') return 'LLM 思考';
      if (msg.kind === 'notice') return '';
      return 'LLM 回复';
    },

    scrollChatToBottom() {
      this.$nextTick(() => {
        const el = this.$refs.chatLog;
        if (el) el.scrollTop = el.scrollHeight;
      });
    },

    getPayload() {
      return {
        report_type:  this.reportType,
        report_style: this.reportStyle,
        metric:       this.metric,
        granularity:  this.granularity,
        start_date:   this.startDate || null,
        end_date:     this.endDate   || null,
        top_n:        Number(this.topN || 10),
        dimensions:   this.selectedDimensions,
      };
    },

    buildCustomTemplateConfig() {
      return {
        id:          (this.tplId   || 'custom_user_template').trim(),
        name:        (this.tplName || '用户自定义模板').trim(),
        description: '用户前端少量配置生成',
        page: {
          size: 'A4',
          margin_cm: [
            Number(this.tplMTop    || 2.5),
            Number(this.tplMRight  || 2.2),
            Number(this.tplMBottom || 2.5),
            Number(this.tplMLeft   || 2.2),
          ],
        },
        fonts: {
          title: { family: '微软雅黑', size_pt: 18, bold: true },
          h1: {
            family:  this.tplH1Font || '微软雅黑',
            size_pt: Number(this.tplH1Size || 15),
            bold: true,
          },
          h2:   { family: '微软雅黑', size_pt: 13, bold: true },
          h3:   { family: '微软雅黑', size_pt: 12, bold: true },
          h4:   { family: '微软雅黑', size_pt: 11, bold: true },
          body: {
            family:  this.tplBodyFont || '宋体',
            size_pt: Number(this.tplBodySize || 11),
            bold: false,
          },
          list: {
            family:  this.tplBodyFont || '宋体',
            size_pt: Number(this.tplBodySize || 11),
            bold: false,
          },
        },
        paragraph_styles: {
          title: { alignment: 'center', line_spacing: 1.2, space_before_pt: 0,  space_after_pt: 18, first_line_indent_chars: 0, keep_with_next: true },
          h1:    { alignment: 'left',   line_spacing: 1.2, space_before_pt: 18, space_after_pt: 6,  first_line_indent_chars: 0, keep_with_next: true },
          h2:    { alignment: 'left',   line_spacing: 1.2, space_before_pt: 12, space_after_pt: 4,  first_line_indent_chars: 0, keep_with_next: true },
          body: {
            alignment:              'justify',
            line_spacing:           Number(this.tplLineSpacing || 1.5),
            space_before_pt:        0,
            space_after_pt:         6,
            first_line_indent_chars: Number(this.tplIndentChars || 2),
          },
          list: { alignment: 'left', line_spacing: 1.3, space_before_pt: 0, space_after_pt: 4, first_line_indent_chars: 0 },
        },
        image: { max_width_cm: 16, alignment: 'center' },
        paragraph: {
          line_spacing:            Number(this.tplLineSpacing || 1.5),
          space_before_pt:         4,
          space_after_pt:          6,
          first_line_indent_chars: Number(this.tplIndentChars || 2),
        },
        header_footer: {
          header: { text: '', alignment: 'center' },
          footer: { show_page_number: true, prefix: '第 ', suffix: ' 页', show_total_pages: false, alignment: 'center' },
        },
      };
    },

    async loadExportTemplates() {
      try {
        const res = await fetch('/api/export/templates');
        if (!res.ok) throw new Error('模板接口异常');
        const j = await res.json();
        const arr = j.templates || [];

        this.userTemplateIds = [];
        if (!arr.length) {
          this.exportTemplates = [{ id: 'cn_management_a4', name: 'cn_management_a4' }];
          if (!this.selectedTemplateId) this.selectedTemplateId = 'cn_management_a4';
          return;
        }

        this.exportTemplates = arr;
        arr.forEach(t => {
          if (t.is_user) this.userTemplateIds.push(t.id);
        });

        if (!this.selectedTemplateId && arr.length > 0) {
          this.selectedTemplateId = arr[0].id;
        }
      } catch (e) {
        console.error('loadExportTemplates failed:', e);
        this.exportTemplates = [{ id: 'cn_management_a4', name: 'cn_management_a4' }];
        if (!this.selectedTemplateId) this.selectedTemplateId = 'cn_management_a4';
      }
    },

    isUserTemplate(id) {
      return this.userTemplateIds.includes(id);
    },

    async deleteTpl() {
      const selectedId = this.selectedTemplateId;
      if (!selectedId || !this.userTemplateIds.includes(selectedId)) return;
      if (!confirm('确定要删除用户模板 "' + selectedId + '" 吗？此操作不可恢复。')) return;
      try {
        const res = await fetch('/api/export/template/delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ template_id: selectedId }),
        });
        const j = await res.json();
        if (!res.ok) { alert(j.message || '删除失败'); return; }
        await this.loadExportTemplates();
      } catch (e) {
        alert('删除失败: ' + (e.message || e));
      }
    },

    async saveTemplate() {
      try {
        const template_config = this.buildCustomTemplateConfig();
        const res = await fetch('/api/export/template/save', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ template_config }),
        });
        const j = await res.json();
        if (!res.ok) { alert(j.message || '保存失败'); return; }
        alert('模板保存成功');
        await this.loadExportTemplates();
        this.selectedTemplateId = template_config.id;
      } catch (e) {
        alert('保存失败: ' + (e.message || e));
      }
    },

    openDesigner() {
      window.open('/template-designer', '_blank');
    },

    async exportDocx() {
      const reportMarkdown = this.getLatestAssistantMarkdown();
      if (!reportMarkdown) {
        alert('没有可导出的报告内容，请先生成报告。');
        return;
      }

      const templateId  = this.selectedTemplateId || 'cn_management_a4';
      const DEFAULT_REPORT_NAME = '数据分析报告';
      const reportTitle = (this.exportTitle || '').trim() || DEFAULT_REPORT_NAME;
      const useCustom   = this.useCustomTpl;
      const customCfg   = useCustom ? this.buildCustomTemplateConfig() : null;

      this.exporting = true;
      try {
        const res = await fetch('/api/export/report', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            report_markdown:    reportMarkdown,
            template_id:        useCustom ? null : templateId,
            template_config:    customCfg,
            report_title:       reportTitle,
            plot_images:        this.buildPlotImages(this.plots),
            plot_images_meta:   this.buildPlotImagesMeta(this.plots),
            selected_dimensions: this.selectedDimensions,
          }),
        });

        if (!res.ok) {
          let msg = '导出失败';
          try { const j = await res.json(); msg = j.message || msg; } catch(e2) {}
          alert(msg);
          return;
        }

        const blob = await res.blob();
        const safeBaseName = String(reportTitle)
          .replace(/[\\/:*?"<>|]+/g, '_')
          .trim();
        const filename = /\.docx$/i.test(safeBaseName) ? safeBaseName : `${safeBaseName}.docx`;

        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url; a.download = filename;
        document.body.appendChild(a); a.click(); a.remove();
        URL.revokeObjectURL(url);
      } catch (e) {
        alert('导出失败: ' + (e.message || e));
      } finally {
        this.exporting = false;
      }
    },

    async refreshCtx() {
      try {
        const res = await fetch('/api/chat/context-check', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            systemPrompt: '你是资深数据分析助手，请严格依据给定报告数据进行回答。',
            messages: this.llmMessages,
          }),
        });
        const j = await res.json();
        this.applyContextStatus(j, { notifyUser: false });
      } catch (e) {
        console.error('refreshCtx failed:', e);
        this.applyContextStatus({
          cumulative_chars_est: 0,
          cumulative_tokens_est: 0,
          limit_tokens_est: 128000,
          level: 'ok',
          message: '上下文状态获取失败，已回退默认值。',
        }, { notifyUser: false });
      }
    },

    async refreshCtxThrottled(force) {
      const now = Date.now();
      if (!force && now - this.lastCtxCheckAt < 2500) return;
      this.lastCtxCheckAt = now;
      await this.refreshCtx();
    },

    onChatInputChange() {
      clearTimeout(this.ctxCheckTimer);
      this.ctxCheckTimer = setTimeout(() => this.refreshCtxThrottled(false), 300);
    },

    getLatestAssistantMarkdown() {
      const reversed = this.llmMessages.slice().reverse();
      const last = reversed.find(function(m) {
        return m.role === 'assistant' && (m.content || '').trim();
      });
      return last ? (last.content || '').trim() : '';
    },

    extractReportTitleFromMarkdown(markdown) {
      const text = String(markdown || '').trim();
      if (!text) return '';
      const lines = text.split(/\r?\n/);
      for (const line of lines) {
        const s = line.replace(/^\s+/, '');
        if (!s.startsWith('# ')) continue;
        const title = s.slice(2).trim();
        if (title) return title;
      }
      return '';
    },

    newSession() {
      this.llmMessages    = [];
      this.displayMessages = [];
      this.chatInput      = '';
      this.plots          = [];
      this.promptText     = PROMPT_TEXT_NOT_GENERATED;
      this.hasPendingGeneratedPrompt = false;
      this.displayMessages.push({
        id: this.nextMsgId++,
        role: 'system',
        kind: 'notice',
        rawContent: '✨ 新对话已创建，请先点击"生成Prompt与图像"，再点击"开始报告生成"',
      });
      this.scrollChatToBottom();
      this.refreshCtxThrottled(true);
    },

    async handleGeneratePrompt() {
      const p = this.getPayload();
      this.plots = [];
      this.promptText = PROMPT_TEXT_GENERATING;
      this.hasPendingGeneratedPrompt = false;

      try {
        const res = await fetch('/api/generate?debug=1', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(p),
        });

        const j = await res.json();

        if (!res.ok || j.error || j.message) {
          this.promptText = PROMPT_TEXT_NOT_GENERATED;
          this.displayMessages.push({
            id: this.nextMsgId++,
            role: 'system',
            kind: 'notice',
            rawContent: '❌ 错误：' + (j.error || j.message || ('HTTP ' + res.status)),
          });
          this.scrollChatToBottom();
          return;
        }

        const promptText = (j.finalPrompt || j.prompt || '').trim();
        this.plots = j.plots || [];

        if (!promptText) {
          this.promptText = PROMPT_TEXT_NOT_RETURNED;
          this.displayMessages.push({
            id: this.nextMsgId++,
            role: 'assistant',
            kind: 'content',
            rawContent: '未拿到可用 prompt，请检查 prompt 模板配置。',
          });
          this.scrollChatToBottom();
          return;
        }

        this.promptText = promptText;
        this.hasPendingGeneratedPrompt = true;

        this.displayMessages.push({
          id: this.nextMsgId++,
          role: 'system',
          kind: 'notice',
          rawContent: '✅ 已生成 Prompt 与图像，请点击"开始报告生成"。',
        });
        this.scrollChatToBottom();
      } catch (e) {
        this.promptText = PROMPT_TEXT_NOT_GENERATED;
        this.hasPendingGeneratedPrompt = false;
        this.displayMessages.push({
          id: this.nextMsgId++,
          role: 'system',
          kind: 'notice',
          rawContent: '❌ 请求失败：' + (e.message || String(e)),
        });
        this.scrollChatToBottom();
      }
    },

    async handleStartReport() {
      if (this.sending) return;
      const promptText = (this.promptText || '').trim();
      if (!this.hasPendingGeneratedPrompt || !promptText || promptText === PROMPT_TEXT_NOT_GENERATED || promptText === PROMPT_TEXT_GENERATING || promptText === PROMPT_TEXT_NOT_RETURNED) {
        this.displayMessages.push({
          id: this.nextMsgId++,
          role: 'system',
          kind: 'notice',
          rawContent: '⚠️ 请先点击"生成Prompt与图像"。',
        });
        this.scrollChatToBottom();
        return;
      }

      this.displayMessages.push({
        id: this.nextMsgId++,
        role: 'user',
        kind: 'content',
        rawContent: promptText,
      });
      this.llmMessages.push({ role: 'user', content: promptText });
      this.hasPendingGeneratedPrompt = false;
      this.scrollChatToBottom();

      await this.refreshCtxThrottled(true);
      await this.runChatSSE('start_report');
    },

    async handleSend() {
      const txt = (this.chatInput || '').trim();
      if (!txt) return;

      this.displayMessages.push({ id: this.nextMsgId++, role: 'user', kind: 'content', rawContent: txt });
      this.llmMessages.push({ role: 'user', content: txt });
      this.chatInput = '';
      this.scrollChatToBottom();

      await this.refreshCtxThrottled(false);
      await this.runChatSSE('chat_followup');
    },

    // ---- SSE Streaming ----
    async runChatSSE(clientTrigger) {
      if (this.sending) return;
      this.sending = true;
      await this.autoCompressHistoryIfNeeded();

      const reasoningId = this.nextMsgId++;
      const contentId   = this.nextMsgId++;

      if (this.showReasoning) {
        this.displayMessages.push({ id: reasoningId, role: 'assistant', kind: 'reasoning', rawContent: '' });
      }
      this.displayMessages.push({ id: contentId, role: 'assistant', kind: 'content', rawContent: '' });
      this.scrollChatToBottom();

      // Helper: find message in displayMessages by id and append text to rawContent
      const appendToMsg = (id, text) => {
        const msg = this.displayMessages.find(m => m.id === id);
        if (msg) msg.rawContent += (text || '');
        this.scrollChatToBottom();
      };

      try {
        const res = await fetch('/api/chat/sse', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            systemPrompt: '你是资深数据分析助手，请严格依据给定报告数据进行回答。',
            messages:     this.llmMessages,
            show_reasoning: this.showReasoning,
            client_trigger: clientTrigger || 'chat_followup',
          }),
        });

        if (!res.ok || !res.body) {
          appendToMsg(contentId, '请求失败：' + res.status);
          return;
        }

        const reader  = res.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let buffer = '';
        let streamDone = false;

        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          let idx;
          while ((idx = buffer.indexOf('\n\n')) >= 0) {
            const raw = buffer.slice(0, idx);
            buffer = buffer.slice(idx + 2);
            const lines = raw.split('\n');
            let ev = 'message', data = '';

            for (const line of lines) {
              if (line.startsWith('event:')) ev = line.slice(6).trim();
              if (line.startsWith('data:'))  data += line.slice(5).trim();
            }

            let obj = null;
            if (data) {
              try { obj = JSON.parse(data); } catch(pe) { continue; }
            }
            if (!obj) continue;

            if (ev === 'notice') {
              this.displayMessages.push({
                id: this.nextMsgId++,
                role: 'system',
                kind: 'notice',
                rawContent: '⚠️ ' + (obj.text || ''),
              });
              this.scrollChatToBottom();
            } else if (ev === 'error') {
              appendToMsg(contentId, '❌ ' + (obj.message || ''));
            } else if (ev === 'reasoning' && this.showReasoning) {
              appendToMsg(reasoningId, obj.text || '');
            } else if (ev === 'content') {
              appendToMsg(contentId, obj.text || '');
            } else if (ev === 'context') {
              this.applyContextStatus(obj, { notifyUser: true });
            } else if (ev === 'meta' && obj.status === 'done') {
              streamDone = true;
              tDone = performance.now();
              break;
            }
          }

          if (streamDone) break;
        }

        // Push final assistant message to llmMessages
        const contentMsg = this.displayMessages.find(m => m.id === contentId);
        const actualContent = contentMsg ? (contentMsg.rawContent || '') : '';
        this.llmMessages.push({ role: 'assistant', content: actualContent });
        await this.refreshCtxThrottled(true);

      } catch (e) {
        appendToMsg(contentId, '❌ 会话请求失败：' + (e.message || e));
      } finally {
        this.sending = false;
      }
    },

    // ---- Query preview modal ----
    async handlePreviewModal() {
      this.showModal    = true;
      this.modalLoading = true;
      this.modalQueries = [];
      this.modalError   = '';

      try {
        const p   = this.getPayload();
        const res = await fetch('/api/query-preview', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(p),
        });
        const j = await res.json();

        if (!res.ok || j.message) {
          this.modalError = '错误：' + (j.message || '请求失败');
          return;
        }

        this.modalQueries = j.queries || [];
      } catch (e) {
        this.modalError = '请求失败: ' + (e.message || String(e));
      } finally {
        this.modalLoading = false;
      }
    },

    // ---- Resizer ----
    startResize(e) {
      this.isResizing = true;
      document.body.style.userSelect = 'none';
    },

    onMouseMove(e) {
      if (!this.isResizing) return;
      const layout = document.querySelector('.layout');
      if (!layout) return;
      const rect = layout.getBoundingClientRect();
      const newWidth = e.clientX - rect.left - 360;
      if (newWidth < 300) return;
      if (rect.width - newWidth - 360 < 300) return;
      this.chatWidth = newWidth;
    },

    onMouseUp() {
      if (this.isResizing) {
        this.isResizing = false;
        document.body.style.userSelect = '';
      }
    },

    onKeyDown(e) {
      if (e.key === 'Escape') this.showModal = false;
    },
  },
}).mount('#app');
