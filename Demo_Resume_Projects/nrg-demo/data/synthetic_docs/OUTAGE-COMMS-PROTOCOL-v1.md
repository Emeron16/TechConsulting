---
doc_id: OUTAGE-COMMS-PROTOCOL
doc_type: outage_procedure
title: "Standard Outage Communication Protocol"
plan_type: null
version: 1
status: active
effective_date: 2025-09-01
---

# Standard Outage Communication Protocol

## 1. Purpose

Defines the standard timeline and channels for communicating with
customers during a routine (non-extreme-weather) electricity outage in
NRG's Texas retail service territories. For extreme weather events (winter
storms, hurricanes), see OUTAGE-WINTER-STORM-PLAYBOOK instead, which
supersedes this protocol's timelines during a declared emergency.

## 2. Communication Timeline (Routine Outage)

| Time Since Outage Start | Required Action |
|---|---|
| Immediately upon detection | SMS + app push notification to affected customers, if outage-detection integration is available for the affected area |
| Within 30 minutes | Outage status published to the customer-facing outage map |
| Within 2 hours | Estimated restoration time (ERT) published, if known; if unknown, customers are told "assessment in progress" rather than a guessed ERT |
| Every 2 hours until restored | ERT updated (or reaffirmed) via SMS/app/outage map |
| Upon restoration | "Power restored" confirmation sent via SMS/app |

## 3. Support Agent Guidance

When a customer calls about an outage:

1. Confirm the customer's service address matches an active outage in the
   outage-map system before describing any ERT.
2. Do not provide an ERT to the customer that is more specific or more
   confident than what is currently published on the outage map — if the
   map says "assessment in progress," tell the customer the same thing,
   even if pressed for a specific time.
3. For any outage affecting a customer with a documented life-support or
   medical-necessity flag on their account, follow ESC-SAFETY-CONCERN
   immediately regardless of outage scale.

## 4. Related Documents

- OUTAGE-WINTER-STORM-PLAYBOOK: Supersedes this protocol during declared
  extreme weather emergencies
- ESC-SAFETY-CONCERN: Escalation path for safety-critical situations
