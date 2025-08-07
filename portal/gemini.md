# Portal App - Detailed Design

This document details the design of the `portal` Django app, which serves as the read-only client-facing dashboard for tracking order progress and viewing details of their animals and products.

## Core Models

The `portal` app does not define its own models. Instead, it interacts with models from other applications (e.g., `reception`, `processing`, `inventory`, `users`) to retrieve and display relevant information to clients.

## App Functionality

*   **Order Progress Tracking:** Clients can view the current status of their `SlaughterOrder`s.
*   **Animal Status Display:** Provides updates on the progress of individual animals within an order, including key milestones (e.g., received, slaughtered).
*   **Weight Information:** Displays recorded weights for animals and carcasses.
*   **Product Details:** Shows details of meat cuts, offal, and by-products associated with their order, including their disposition (e.g., returned to owner, for sale).
*   **Client-Specific Views:** Ensures that clients can only access information related to their own orders and animals.
*   **User Authentication:** Leverages the `users` app for client login and authentication to secure access to their data.
