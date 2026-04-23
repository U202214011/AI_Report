const { createApp } = Vue;
createApp({
  delimiters: ['[[', ']]'],
  data() {
    return {
      tplId: 'my_tpl',
      tplName: '我的模板',
      tplList: [],
      selectedLoadId: '',
      userTplIds: [],

      title_font: '微软雅黑', title_size: 18, title_color: '#000000',
      title_bold: true, title_italic: false, title_align: 'center',
      title_lsp: 1.2, title_sb: 0, title_sa: 18, title_indent: 0,

      h1_font: '微软雅黑', h1_size: 15, h1_color: '#000000',
      h1_bold: true, h1_italic: false, h1_align: 'left',
      h1_lsp: 1.2, h1_sb: 18, h1_sa: 6, h1_indent: 0,

      h2_font: '微软雅黑', h2_size: 13, h2_color: '#000000',
      h2_bold: true, h2_italic: false, h2_align: 'left',
      h2_lsp: 1.2, h2_sb: 12, h2_sa: 4, h2_indent: 0,

      h3_font: '微软雅黑', h3_size: 12, h3_color: '#000000',
      h3_bold: true, h3_italic: false, h3_align: 'left',
      h3_lsp: 1.2, h3_sb: 10, h3_sa: 4, h3_indent: 0,

      h4_font: '微软雅黑', h4_size: 11, h4_color: '#000000',
      h4_bold: true, h4_italic: false, h4_align: 'left',
      h4_lsp: 1.2, h4_sb: 8, h4_sa: 4, h4_indent: 0,

      body_font: '宋体', body_size: 11, body_color: '#000000',
      body_bold: false, body_italic: false, body_align: 'justify',
      line_spacing: 1.5, body_sb: 0, body_sa: 6, indent_chars: 2,

      list_font: '宋体', list_size: 11, list_color: '#000000',
      list_bold: false, list_italic: false,

      page_size: 'A4', page_orient: 'portrait',
      m_top: 2.5, m_right: 2.2, m_bottom: 2.5, m_left: 2.2,

      header_text: '', header_align: 'center',
      footer_pagenum: true, footer_total: false,
      footer_prefix: '第 ', footer_suffix: ' 页', footer_align: 'center',

      preview_md: `# 一、概览
本季度销售额同比增长 **12.8%**。

# 二、维度分析
## 流派
- 摇滚与流行流派销售贡献最高
- 经典流派复购表现稳定

## 国家
- 北美区域增长明显
- 亚太区域潜力较高

# 三、建议
1. 深耕高增长区域
2. 对低增长客户做分层运营`,

      autoPreview: false,
      statusMsg: '', statusOk: true, errorMsg: '',
      liveDot: false, metaInfo: '等待预览...', previewBusy: false,
      previewInflight: false, previewQueued: false, saveInflight: false,
      requestSeq: 0, previewTimer: null,
    };
  },
  computed: {
    cfgSnapshot() { return JSON.stringify(this.buildCfgObject()); },
    canDeleteLoadedTpl() { return this.isUserTpl(this.selectedLoadId); }
  },
  watch: {
    cfgSnapshot() { this.schedulePreview(); },
    preview_md() { this.schedulePreview(); }
  },
  async mounted() {
    await this.refreshTplList();
    try {
      this._bc = new BroadcastChannel('tpl_saved');
      this._bc.onmessage = () => this.refreshTplList();
    } catch(e) {}
  },
  methods: {
    colorVal(v) { const s = (v || '').trim(); return s || undefined; },
    cfg() { return this.buildCfgObject(); },
    buildCfgObject() {
      return {
        id: (this.tplId || '').trim() || 'my_tpl',
        name: (this.tplName || '').trim() || '我的模板',
        description: '模板配置中心保存',
        page: {
          size: this.page_size || 'A4',
          orientation: this.page_orient || 'portrait',
          margin_cm: [Number(this.m_top)||2.5, Number(this.m_right)||2.2, Number(this.m_bottom)||2.5, Number(this.m_left)||2.2]
        },
        fonts: {
          title: { family: this.title_font||'微软雅黑', size_pt: Number(this.title_size)||18, bold: this.title_bold, italic: this.title_italic, color: this.colorVal(this.title_color) },
          h1:    { family: this.h1_font   ||'微软雅黑', size_pt: Number(this.h1_size)   ||15, bold: this.h1_bold,    italic: this.h1_italic,    color: this.colorVal(this.h1_color)    },
          h2:    { family: this.h2_font   ||'微软雅黑', size_pt: Number(this.h2_size)   ||13, bold: this.h2_bold,    italic: this.h2_italic,    color: this.colorVal(this.h2_color)    },
          h3:    { family: this.h3_font   ||'微软雅黑', size_pt: Number(this.h3_size)   ||12, bold: this.h3_bold,    italic: this.h3_italic,    color: this.colorVal(this.h3_color)    },
          h4:    { family: this.h4_font   ||'微软雅黑', size_pt: Number(this.h4_size)   ||11, bold: this.h4_bold,    italic: this.h4_italic,    color: this.colorVal(this.h4_color)    },
          body:  { family: this.body_font ||'宋体',              size_pt: Number(this.body_size) ||11, bold: this.body_bold,  italic: this.body_italic,  color: this.colorVal(this.body_color)  },
          list:  { family: this.list_font ||'宋体',              size_pt: Number(this.list_size) ||11, bold: this.list_bold,  italic: this.list_italic,  color: this.colorVal(this.list_color)  }
        },
        paragraph_styles: {
          title: { alignment: this.title_align||'center',  line_spacing: Number(this.title_lsp)||1.2, space_before_pt: Number(this.title_sb)||0,  space_after_pt: Number(this.title_sa)||18, first_line_indent_chars: Number(this.title_indent)||0, keep_with_next: true  },
          h1:    { alignment: this.h1_align   ||'left',    line_spacing: Number(this.h1_lsp)   ||1.2, space_before_pt: Number(this.h1_sb)   ||18, space_after_pt: Number(this.h1_sa)   ||6,  first_line_indent_chars: Number(this.h1_indent)   ||0, keep_with_next: true  },
          h2:    { alignment: this.h2_align   ||'left',    line_spacing: Number(this.h2_lsp)   ||1.2, space_before_pt: Number(this.h2_sb)   ||12, space_after_pt: Number(this.h2_sa)   ||4,  first_line_indent_chars: Number(this.h2_indent)   ||0, keep_with_next: true  },
          h3:    { alignment: this.h3_align   ||'left',    line_spacing: Number(this.h3_lsp)   ||1.2, space_before_pt: Number(this.h3_sb)   ||10, space_after_pt: Number(this.h3_sa)   ||4,  first_line_indent_chars: Number(this.h3_indent)   ||0, keep_with_next: false },
          h4:    { alignment: this.h4_align   ||'left',    line_spacing: Number(this.h4_lsp)   ||1.2, space_before_pt: Number(this.h4_sb)   ||8,  space_after_pt: Number(this.h4_sa)   ||4,  first_line_indent_chars: Number(this.h4_indent)   ||0, keep_with_next: false },
          body:  { alignment: this.body_align ||'justify', line_spacing: Number(this.line_spacing)||1.5, space_before_pt: Number(this.body_sb)||0, space_after_pt: Number(this.body_sa)||6, first_line_indent_chars: Number(this.indent_chars)||2 },
          list:  { alignment: 'left', line_spacing: 1.3, space_before_pt: 0, space_after_pt: 4, first_line_indent_chars: 0 }
        },
        header_footer: {
          header: { text: this.header_text||'', alignment: this.header_align||'center' },
          footer: { show_page_number: this.footer_pagenum, prefix: this.footer_prefix, suffix: this.footer_suffix, show_total_pages: this.footer_total, alignment: this.footer_align||'center' }
        },
        image: { max_width_cm: 16, alignment: 'center' },
        paragraph: { line_spacing: Number(this.line_spacing)||1.5, space_before_pt: 4, space_after_pt: 6, first_line_indent_chars: Number(this.indent_chars)||2 }
      };
    },
    async doPreviewDocxCore() {
      const seq = ++this.requestSeq;
      this.errorMsg = '';
      this.setStatus('正在生成预览...');
      this.metaInfo = '请求后端生成 DOCX...';
      this.liveDot = false;
      this.previewBusy = true;
      try {
        if (typeof docx === 'undefined' || !docx.renderAsync) throw new Error('docx-preview 未加载成功（docx.renderAsync 不可用）');
        const res = await fetch('/api/export/template/preview-docx', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ template_config: this.cfg(), report_title: '2026Q1 销售分析报告', report_markdown: this.preview_md || '# 一、概览\n这是一段正文预览。' })
        });
        if (!res.ok) { const j = await res.json().catch(()=>({})); throw new Error(j.message||('HTTP '+res.status)); }
        const arr = await res.arrayBuffer();
        if (seq < this.requestSeq) return;
        const previewEl = this.$refs.docxPreview;
        previewEl.innerHTML = '';
        await docx.renderAsync(arr, previewEl, null, { className: 'docx', inWrapper: true, breakPages: true, ignoreWidth: false, ignoreHeight: false, ignoreFonts: false });
        this.liveDot = true;
        const kb = (arr.byteLength/1024).toFixed(1);
        this.metaInfo = `预览已更新 · ${kb} KB`;
        this.setStatus('预览成功');
      } catch(e) {
        const msg = e?.message || String(e);
        this.setStatus('预览失败', false);
        this.errorMsg = '预览失败： ' + msg;
        this.metaInfo = '预览失败';
        console.error(e);
      } finally { this.previewBusy = false; }
    },
    async previewDocx() {
      if (this.previewInflight) { this.previewQueued = true; return; }
      this.previewInflight = true;
      try { await this.doPreviewDocxCore(); } finally { this.previewInflight = false; }
      if (this.previewQueued) { this.previewQueued = false; this.previewDocx(); }
    },
    async saveTpl() {
      if (this.saveInflight) return;
      this.saveInflight = true;
      this.setStatus('正在保存模板...');
      this.errorMsg = '';
      try {
        const res = await fetch('/api/export/template/save', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ template_config: this.cfg() })
        });
        const j = await res.json().catch(()=>({}));
        if (!res.ok) throw new Error(j.message||('HTTP '+res.status));
        this.setStatus('模板已保存');
        alert('模板已保存');
        try { const bc = new BroadcastChannel('tpl_saved'); bc.postMessage({ts:Date.now()}); bc.close(); } catch(e){}
        try { localStorage.setItem('tpl_saved', Date.now()); } catch(e){}
      } catch(e) {
        const msg = e?.message || String(e);
        this.setStatus('保存失败', false);
        this.errorMsg = '保存失败： ' + msg;
      } finally { this.saveInflight = false; }
    },
    schedulePreview() {
      if (!this.autoPreview) return;
      clearTimeout(this.previewTimer);
      this.previewTimer = setTimeout(() => this.previewDocx(), 600);
    },
    async refreshTplList() {
      try {
        const res = await fetch('/api/export/templates');
        const j = await res.json();
        const arr = j.templates || [];
        this.userTplIds = arr.filter(t => t.is_user).map(t => t.id);
        this.tplList = arr;
      } catch(e) { console.error('加载模板列表失败', e); }
    },
    isUserTpl(id) { return this.userTplIds.includes(id); },
    async loadTpl() {
      const id = this.selectedLoadId;
      if (!id) return;
      try {
        const res = await fetch('/api/export/template/' + encodeURIComponent(id));
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const c = await res.json();
        this.fillForm(c);
        this.setStatus('模板已加载: ' + (c.name || id));
        this.schedulePreview();
      } catch(e) { this.setError('加载失败: ' + (e.message||e)); }
    },
    fillForm(c) {
      if (!c) return;
      if (c.id   != null) this.tplId   = c.id;
      if (c.name != null) this.tplName = c.name;
      const ff = (p, f) => {
        f = f||{};
        if (f.family  != null) this[p+'_font']   = f.family;
        if (f.size_pt != null) this[p+'_size']   = f.size_pt;
        if (f.bold    != null) this[p+'_bold']   = !!f.bold;
        if (f.italic  != null) this[p+'_italic'] = !!f.italic;
        if (f.color)           this[p+'_color']  = f.color;
      };
      const fon = c.fonts||{};
      ff('title',fon.title); ff('h1',fon.h1); ff('h2',fon.h2); ff('h3',fon.h3); ff('h4',fon.h4); ff('body',fon.body); ff('list',fon.list);
      const fp = (p, s) => {
        s = s||{};
        if (s.alignment               != null) this[p+'_align']  = s.alignment;
        if (s.line_spacing            != null) this[p+'_lsp']    = s.line_spacing;
        if (s.space_before_pt         != null) this[p+'_sb']     = s.space_before_pt;
        if (s.space_after_pt          != null) this[p+'_sa']     = s.space_after_pt;
        if (s.first_line_indent_chars != null) this[p+'_indent'] = s.first_line_indent_chars;
      };
      const ps = c.paragraph_styles||{};
      fp('title',ps.title); fp('h1',ps.h1); fp('h2',ps.h2); fp('h3',ps.h3); fp('h4',ps.h4);
      const pb = ps.body||{};
      if (pb.alignment               != null) this.body_align  = pb.alignment;
      if (pb.line_spacing            != null) this.line_spacing = pb.line_spacing;
      if (pb.space_before_pt         != null) this.body_sb      = pb.space_before_pt;
      if (pb.space_after_pt          != null) this.body_sa      = pb.space_after_pt;
      if (pb.first_line_indent_chars != null) this.indent_chars = pb.first_line_indent_chars;
      const pg = c.page||{};
      if (pg.size        != null) this.page_size   = pg.size;
      if (pg.orientation != null) this.page_orient = pg.orientation;
      const m = pg.margin_cm||[];
      if (m.length===4) { this.m_top=m[0]; this.m_right=m[1]; this.m_bottom=m[2]; this.m_left=m[3]; }
      const hf = c.header_footer||{};
      const hdr = hf.header||{};
      if (hdr.text      != null) this.header_text  = hdr.text;
      if (hdr.alignment != null) this.header_align = hdr.alignment;
      const ftr = hf.footer||{};
      if (ftr.show_page_number != null) this.footer_pagenum = !!ftr.show_page_number;
      if (ftr.prefix           != null) this.footer_prefix  = ftr.prefix;
      if (ftr.suffix           != null) this.footer_suffix  = ftr.suffix;
      if (ftr.show_total_pages != null) this.footer_total   = !!ftr.show_total_pages;
      if (ftr.alignment        != null) this.footer_align   = ftr.alignment;
    },
    async deleteTpl() {
      const id = this.selectedLoadId;
      if (!id || !this.isUserTpl(id)) return;
      if (!confirm('确定要删除用户模板 "' + id + '" 吗？此操作不可恢复。')) return;
      try {
        const res = await fetch('/api/export/template/delete', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ template_id: id })
        });
        const j = await res.json().catch(()=>({}));
        if (!res.ok) throw new Error(j.message||('HTTP '+res.status));
        this.setStatus('模板已删除');
        this.selectedLoadId = '';
        await this.refreshTplList();
      } catch(e) { this.setError('删除失败: ' + (e.message||e)); }
    },
    setStatus(msg, ok=true) { this.statusMsg = msg||''; this.statusOk = ok; },
    setError(msg) { this.errorMsg = msg||''; }
  }
}).mount('#app');
