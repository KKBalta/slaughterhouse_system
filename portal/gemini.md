# App: portal

## Purpose
Provides a read-only dashboard for clients to track the real-time status of their `SlaughterOrder` and the individual animals within it.

## Core Models
This app will not have its own models. It will only provide views that read data from the `reception` and `processing` apps.

## Key Logic
- A login-protected view.
- The main dashboard will list the user's active and past `SlaughterOrder`s.
- A detail view for each order, showing a list of all `Animal`s and their current `status` and `WeightLog` entries.