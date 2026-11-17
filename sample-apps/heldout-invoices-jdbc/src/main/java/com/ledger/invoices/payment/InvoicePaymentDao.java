package com.ledger.invoices.payment;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.util.Optional;

@Repository
public class InvoicePaymentDao {

    private final JdbcTemplate jdbc;

    public InvoicePaymentDao(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public Optional<InvoicePayment> find(String invoiceNo) {
        return jdbc.query("SELECT * FROM invoice_payment WHERE invoice_no = ?",
                (rs, i) -> new InvoicePayment(rs.getString("invoice_no"), rs.getLong("amount_minor"),
                        rs.getString("currency"), rs.getString("psp"), rs.getString("psp_reference"),
                        rs.getString("status")), invoiceNo).stream().findFirst();
    }

    public void insert(InvoicePayment p) {
        jdbc.update("INSERT INTO invoice_payment (invoice_no, amount_minor, currency, psp, psp_reference, status) "
                + "VALUES (?, ?, ?, ?, ?, ?)", p.invoiceNo(), p.amountMinor(), p.currency(), p.psp(), p.pspReference(), p.status());
    }

    public void updateStatus(String invoiceNo, String status) {
        jdbc.update("UPDATE invoice_payment SET status = ? WHERE invoice_no = ?", status, invoiceNo);
    }
}
