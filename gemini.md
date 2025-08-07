# Slaughterhouse System - Main Design Plan

This document outlines the high-level architecture and core functionalities of the Slaughterhouse Management System. The project is built on Django and is designed to be modular, with each Django app representing a distinct domain of the business.

## Project Principles

1.  **Modularity:** Each app has a single, well-defined responsibility.
2.  **Clear APIs:** Apps interact through well-defined functions and services.
3.  **Test-Driven:** All new functionality is accompanied by tests.
4.  **Agent-Friendly:** Code and documentation are clear and structured for AI development.

## App Architecture Overview

| App Name      | Primary Responsibility                                           | Key Entities/Concepts Handled     |
| :------------ | :--------------------------------------------------------------- | :-------------------------------- |
| **`users`**       | User management, authentication, authorization, and client profiles. | `User`, `ClientProfile`           |
| **`reception`**   | Client intake, creation and management of slaughter orders.      | `SlaughterOrder`, `ServicePackage`|
| **`processing`**  | Tracking animals through the slaughter workflow.                 | `Animal`, `WeightLog`             |
| **`portal`**      | Read-only client-facing dashboard for order progress.            | (Views for client access)         |
| **`inventory`**   | Manages post-slaughter assets and their disposition.             | `Carcass`, `MeatCut`, `Offal`, `ByProduct`, `Label`|
| **`core`**        | Shared utilities, base models, and common functionalities.       | `BaseModel` (abstract)            |
| **`labeling`**    | Generating and printing labels for assets.                       | `LabelTemplate`, `PrintJob`       |
| **`reporting`**   | Generating comprehensive internal reports and analytics.         | `Report`, `Dashboard`             |

## High-Level Business Workflow

The system supports a flexible workflow, allowing clients to select specific services. The core process involves:

1.  **Order Creation (Reception):** A clerk creates a `SlaughterOrder` for a client (new or existing), selecting a `ServicePackage` and specifying the group of animals (e.g., 2 cattle, 10 sheep).
2.  **Animal Intake & Tracking (Processing):** Individual animals are recorded, identified, and linked to the `SlaughterOrder`. Their journey through the slaughter process is tracked, including various weighings (individual or group).
3.  **Conditional Processing (Processing & Inventory):** Based on the selected `ServicePackage`, the system orchestrates the workflow. For example, if disassembly is requested, the carcass is broken down into `MeatCut`s, `Offal`, and `ByProduct`s.
4.  **Asset Management & Disposition (Inventory):** All generated assets (carcasses, cuts, by-products) are managed, their weights logged, and their final disposition (e.g., returned to owner, for sale) is recorded.
5.  **Labeling (Labeling):** Labels are generated and printed for various assets as needed.
6.  **Client Monitoring (Portal):** Clients can view the real-time progress of their orders and the status of their assets through a dedicated portal.
7.  **Reporting (Reporting):** Internal reports are generated to provide insights into operations, yield, and financial performance.

## Key Design Considerations

*   **Modular Service Offerings:** The `ServicePackage` concept allows clients to choose specific services, dynamically influencing the workflow steps.
*   **Diverse Animal Types:** The system accommodates various animal types (cattle, sheep, goat, lamb, oglak) with dedicated models for species-specific details.
*   **Flexible Weighing:** Supports both individual animal weighing and group weighing for smaller animals, with average weight calculation for individual tracking.
*   **Client Management:** Handles both one-time and loyal customers through the `ClientProfile`.