# EnviroPulse Server README

## 1. Server Purpose

The EnviroPulse server is the coordination layer between field nodes, GUIs, 
storage, system state, and analysis. It receives events from GUIs and nodes, 
routes those events through internal subsystems, records activity, 
updates live platform state, and sends commands or results back out.

The server is designed around event movement. Each subsystem has a focused
role and communicates through named events rather than direct dependency on 
every other subsystem.

---

## 2. High-Level Flow

```text
GUI / Node
   ↓
Communication Listener
   ↓
Server Event Bus
   ↓
Registry / Journal / Database / TDOA
   ↓
Communication Sender
   ↓
GUI / Node
```

Inbound packets enter through the Communication Listener. The listener converts them into server events and publishes them to the event bus. Subsystems that subscribe to those events react as needed. Some events update live state, some are recorded, some are analyzed, and some are sent back out through the Communication Sender.

---

## 3. Subsystem Summary

| Subsystem              | Responsibility                                        |
| ---------------------- | ----------------------------------------------------- |
| Communication Listener | Receives inbound GUI and node packets.                |
| Platform Registry      | Tracks known GUIs, nodes, and live platform state.    |
| Event Journal          | Displays and records the server event timeline.       |
| Database               | Stores durable records.                               |
| TDOA                   | Evaluates multi-node detections for localization.     |
| Communication Sender   | Sends commands, acknowledgments, and results outward. |

---

## 4. Event Categories

Server events are organized into three main categories.

| Category | Meaning                              |
| -------- | ------------------------------------ |
| State    | Reports what something currently is. |
| Event    | Reports that something happened.     |
| Mode     | Requests a change in behavior.       |

Examples:

```text
State: NODE_HEARTBEAT, GPS_LOCK, GPS_COORD, TEMP_AVAILABLE
Event: GUI_REGISTER, GUI_REGISTERED, REGISTRY_UPDATED, AVIS_LITE
Mode: WIFI_MODE_CHANGE, LORA_MODE_CHANGE, TDOA_MODE_CHANGE
```

This separation keeps the server readable. A state event describes current condition, an event announces activity, and a mode event asks part of the system to change behavior.

---

## 5. Current Server Scope

Current server work focuses on GUI registration, mode-change routing, event journaling, platform registry updates, database handoff, communication sender routing, and simulated node events.

The server is being built to support future field-node communication, acoustic detections, environmental data, GPS/RTK state, PPS timing, and TDOA localization. Not every future event is fully implemented yet, but the event structure is designed to allow those pieces to be added without rewriting the full server.

---

## 6. Where to Look Next

For event names and payload expectations, see the server event contract.

For live event movement, see the server event timeline drawing.

For implementation details, inspect each subsystem folder:

```text
communication_listener/
communication_sender/
platform_registry/
event_journal/
database/
tdoa/
```

The README provides the system overview. The event contract defines the exact event rules. The timeline drawing shows how events move through the server.
