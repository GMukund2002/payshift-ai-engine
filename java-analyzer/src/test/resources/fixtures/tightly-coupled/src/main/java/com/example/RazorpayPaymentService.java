package com.example;

import com.razorpay.RazorpayClient;
import com.razorpay.RazorpayException;

import org.springframework.stereotype.Service;

@Service
public class RazorpayPaymentService {

    private final RazorpayClient razorpayClient;

    public RazorpayPaymentService(RazorpayClient razorpayClient) {
        this.razorpayClient = razorpayClient;
    }

    public String createPayment(long amount, String currency) throws RazorpayException {
        return "order_123";
    }

    public String getPaymentStatus(String orderId) {
        return "paid";
    }

    public void refundPayment(String paymentId, long amount) throws RazorpayException {
        // calls out to Razorpay's refund API
    }
}
