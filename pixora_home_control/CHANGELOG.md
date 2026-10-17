# 1.0.8

- Send each Home Assistant event once using one event-bus subscription, preserving state triggers, Lutron buttons, custom events and notification replies.
- Uses the optimized stream with Pixora cloud 1.42.366 or newer; automatically retains the compatible stream on older servers.

# 1.0.7

- Forward Home Assistant events for Flows Event nodes and safely correlated notification action responses.
- Preserve events received during subscription setup and retain reconnect recovery.
- Requires the matching Pixora cloud update before updating this app.

# 1.0.6

- Recover automatically when Pixora or Home Assistant closes a socket during authentication or event subscription, instead of exiting with WSMessageTypeError.
- Report which handshake connection closed and its close code without logging credentials or server payloads.

# 1.0.5

- Discover Lutron button controllers and forward their live button events to Flows.

# 1.0.4

- Reset reconnect backoff after sessions lasting at least 60 seconds.
- Log which connection closed, its close code, and the reconnect delay without exposing credentials.

# 1.0.3

- Read complete local HTTP responses before decoding JSON, preserving the response size limit. Fixes fragmented device-state and service catalog reads.

# 1.0.2

- Report specific local request failures, HTTP status, and request path in logs without exposing credentials or response bodies.

# 1.0.1

- Publish the app in its own public installation repository.

# 1.0.0

- Pair with Planner and connect outbound to Pixora.
- Send local Home Assistant events to the existing Flow engine.
- Execute shared Planner, Home Control, and Flow requests locally.
- Reconnect automatically; reject expired commands and duplicate IDs.
