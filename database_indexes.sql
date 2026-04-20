-- 为 Invoice 表添加索引
-- InvoiceId 是主键，应该已经有索引
CREATE INDEX idx_invoice_invoice_date ON Invoice(InvoiceDate);
CREATE INDEX idx_invoice_customer_id ON Invoice(CustomerId);
