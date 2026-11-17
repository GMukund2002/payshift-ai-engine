CREATE TABLE IF NOT EXISTS invoice_payment (
    invoice_no VARCHAR(64) PRIMARY KEY,
    amount_minor BIGINT NOT NULL,
    currency VARCHAR(8) NOT NULL,
    psp VARCHAR(32) NOT NULL,
    psp_reference VARCHAR(128),
    status VARCHAR(32) NOT NULL
);
