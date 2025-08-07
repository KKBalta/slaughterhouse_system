# Slaughterhouse System - System Design

This document outlines the high-level architecture for the Slaughterhouse Management System. The project is built on Django and is designed to be modular, with each Django app representing a core domain of the business.

## Project Principles

1.  **Modularity:** Each app should have a single, well-defined responsibility.
2.  **Clear APIs:** Apps should interact with each other through well-defined functions and services, not by reaching directly into each other's models unless absolutely necessary (e.g., via ForeignKeys).
3.  **Test-Driven:** All new functionality should be accompanied by tests.
4.  **Agent-Friendly:** The code and documentation should be clear and structured to facilitate development by AI agents.

## App Architecture

| App Name      | Responsibility                                                                   | Core Models                      |
| :------------ | :------------------------------------------------------------------------------- | :------------------------------- |
| **`users`**       | User management, authentication, authorization, and profiles.                    | `User`, `ClientProfile`          |
| **`reception`**   | Client intake, creating and managing slaughter orders ("Tabs").                  | `SlaughterOrder`                 |
| **`processing`**  | Tracking individual animals through the slaughter workflow.                      | `Animal`, `WeightLog`            |
| **`portal`**      | The read-only client-facing dashboard for tracking order progress.               | (No models, provides views)      |
| **`inventory`**   | Manages post-slaughter assets, including carcass labeling and storage tracking.  | `Carcass`, `Label`               |
| **`core`**        | Shared utilities, base models, custom management commands, and static assets.    | `BaseModel` (abstract)           |