---
doc_id: ESC-SAFETY-CONCERN
doc_type: escalation_playbook
title: "Safety Concern Escalation Playbook (Downed Lines, Gas Odor, Medical Necessity)"
plan_type: null
version: 1
status: active
effective_date: 2025-08-01
---

# Safety Concern Escalation Playbook (Downed Lines, Gas Odor, Medical Necessity)

## 1. Purpose

Defines the immediate-escalation path for any customer contact involving a
genuine safety hazard, distinct from a standard outage or billing inquiry.
This playbook takes priority over any other in-progress workflow.

## 2. Immediate-Escalation Triggers

Any of the following must be escalated immediately, interrupting whatever
else the agent was doing on the call:

- **Downed power line** — instruct the customer to stay at least 35 feet
  away and treat it as energized regardless of appearance; do not attempt
  to assess whether it is "probably fine"
- **Gas odor** — this is outside NRG's scope (NRG is an electricity
  retailer, not a gas utility), but agents must still instruct the
  customer to evacuate and call 911 or the local gas utility's emergency
  line immediately, and log the contact
- **Medical-necessity / life-support dependency during an outage** — a
  customer or household member depends on powered medical equipment
  (oxygen concentrator, dialysis, etc.)
- **Reported injury** related to electrical equipment or a downed line

## 3. Agent Actions

1. For downed lines or gas odors: advise the customer to move to a safe
   distance and contact 911 / emergency services directly — do not tell
   the customer to wait for NRG before taking safety action.
2. For medical-necessity outage situations: confirm the account's
   medical-necessity flag (or take the report if unflagged and add the
   flag for future reference), and escalate to the Priority Restoration
   queue referenced in OUTAGE-COMMS-PROTOCOL and
   OUTAGE-WINTER-STORM-PLAYBOOK.
3. Every safety escalation must be logged with a timestamp and outcome,
   regardless of how it was ultimately resolved.

## 4. What This Playbook Is Not For

Do not use this escalation path for routine outage status questions with
no safety element, or for billing disputes — route those per
OUTAGE-COMMS-PROTOCOL or ESC-BILLING-DISPUTE respectively.

## 5. Related Documents

- OUTAGE-COMMS-PROTOCOL: Standard outage communication protocol
- OUTAGE-WINTER-STORM-PLAYBOOK: Emergency-weather outage protocol
