---
title: Mapping a Shared Network Drive
category: Storage & Files
last_updated: 2026-06-02
tags: [shared drive, network drive, file server, storage]
---

# Mapping a Shared Network Drive

TechConsulting stores departmental files on two central file servers: `\\tc-fs01\shared` (company-wide shared folders) and `\\tc-fs02\projects` (active client project folders). Employees who need regular access to these folders should map them as a network drive so they appear in File Explorer like a local disk.

## Before you start

You must be connected to the TechConsulting office network or the TC SecureConnect VPN (see the VPN article) to reach the file servers. Confirm with your manager which folder and drive letter your team standardizes on — most departments use `S:` for `\\tc-fs01\shared` and `P:` for `\\tc-fs02\projects`.

## Steps (Windows)

1. Open File Explorer.
2. Click **This PC**, then select **Map network drive** from the ribbon.
3. Choose an unused drive letter (commonly `S:` for shared or `P:` for projects).
4. In the Folder field, enter the full path, for example `\\tc-fs01\shared\marketing`.
5. Check **Reconnect at sign-in** so the drive remains mapped after restarts.
6. Click **Finish**. If prompted, sign in with your TechConsulting network credentials (`firstname.lastname` and your standard password).

## Troubleshooting

If you receive "network path not found," confirm you're on the VPN or office network. If you receive "access denied," your account may not have permissions on that folder — submit a request through the TC Helpdesk Portal (helpdesk.techconsulting.com) specifying the exact folder path and the business reason.

For questions, contact IT Support at [email protected] or extension 4357.
