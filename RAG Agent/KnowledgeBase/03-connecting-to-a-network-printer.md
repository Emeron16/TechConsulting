---
title: Connecting to a Network Printer
category: Hardware & Peripherals
last_updated: 2026-05-18
tags: [printer, network printer, print queue, hardware]
---

# Connecting to a Network Printer

Once the correct driver is installed (see "Installing a Printer Driver"), you can add any TechConsulting network printer by connecting to its shared queue on the print server `tc-print01`.

## Finding your printer's queue name

Printer queue names follow the pattern `floor-wing-model`, for example `3F-East-HPLaserJet` or `1F-Lobby-XeroxVersaLink`. Queue names are posted on a label on each physical printer, or you can ask your office manager.

## Steps (Windows)

1. Open **Settings > Bluetooth & devices > Printers & scanners**.
2. Click **Add device**.
3. If the printer doesn't appear automatically, select **Select a shared printer by name** and enter `\\tc-print01\<queue-name>`, for example `\\tc-print01\3F-East-HPLaserJet`.
4. Click **Next** and allow Windows to connect and finish installing the queue.
5. Print a test page to confirm the connection.

## Notes

You must be on the office network or TC SecureConnect VPN to reach `tc-print01`. If the printer fails to connect after the driver is installed, the queue name may be mistyped, or the print server may be temporarily unavailable — check the IT status page at status.techconsulting.com before submitting a ticket.

For questions, contact IT Support at [email protected] or extension 4357.
