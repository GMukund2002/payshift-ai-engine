package com.example;

/** Deliberately named "Order" (no com.razorpay import) to verify the analyzer
 * doesn't misattribute this generic domain class to Razorpay just because its
 * name happens to collide with a real Razorpay SDK class name. */
public class Order {
    private String id;
    private long amount;
}
