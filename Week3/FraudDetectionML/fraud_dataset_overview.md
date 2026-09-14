# Fraud Transaction Intent Classification — Dataset Overview

**Domain:** Finance
**Problem Type:** Binary Classification
**Total Rows:** 15,000
**Total Columns:** 18

---

## About the Dataset

This dataset contains financial transaction records labeled for fraud detection. Each row represents a single transaction captured across various behavioral, geographic, device, and authentication-related attributes. The goal is to classify whether a given transaction is fraudulent or legitimate based on the available features.

---

## Column Descriptions

| # | Column | Description |
|---|---|---|
| 1 | `transaction_id` | Unique identifier for each transaction |
| 2 | `transaction_amount` | The monetary value of the transaction in USD |
| 3 | `transaction_hour` | The hour of the day (0–23) when the transaction was made |
| 4 | `device_type` | The type of device used to initiate the transaction |
| 5 | `location_mismatch` | Indicates whether the transaction location differs from the cardholder's registered address |
| 6 | `previous_fraud_flags` | The number of past fraud flags associated with the account |
| 7 | `velocity_last_1hr` | The number of transactions made by the user in the past hour |
| 8 | `merchant_category` | The category of the merchant involved in the transaction |
| 9 | `card_type` | The type of payment card used |
| 10 | `account_age_days` | The age of the account in days at the time of the transaction |
| 11 | `failed_auth_attempts` | The number of failed authentication attempts prior to this transaction |
| 12 | `ip_country_match` | Whether the IP address country matches the card-issuing country |
| 13 | `amount_deviation_ratio` | How much the transaction amount deviates from the user's historical average |
| 14 | `transaction_channel` | The channel through which the transaction was conducted |
| 15 | `is_weekend` | Whether the transaction took place on a weekend |
| 16 | `distance_from_home_km` | The distance in kilometers between the transaction location and the user's home |
| 17 | `cvv_match` | Whether the CVV provided matched the card's CVV |
| 18 | `is_fraudulent_transaction` | **Target** — Whether the transaction is fraudulent (1) or legitimate (0) |

---

