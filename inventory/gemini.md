# Inventory App – Design Plan

This document defines the high-level architecture, core concepts, and business workflow of the `inventory` app within the Slaughterhouse Management System.

## 1. App Architecture Overview

| App Name | Responsibility |
| :--- | :--- |
| `inventory` | Manages post-slaughter assets, packaging, storage, and disposition. |

## 2. Key Entities / Concepts

*   **`Carcass`**: Represents the whole body of a slaughtered animal after initial processing.
*   **`MeatCut`**: Individual portions of meat derived from a `Carcass`.
*   **`Offal`**: Edible or inedible organs and entrails from a slaughtered animal.
*   **`ByProduct`**: Other valuable products derived from the animal (e.g., skin, head, feet).
*   **`StorageLocation`**: Defines physical locations within the facility where inventory items are stored (e.g., freezers, coolers).

## 3. High-Level Business Workflow (Inventory Specific)

The `inventory` app takes over after the `processing` app has completed the slaughter and initial carcass preparation. Its workflow focuses on managing the derived products:

1.  **Carcass Intake:** A `Carcass` is received from the `processing` stage, typically after hot and cold weighing.
2.  **Disassembly:** Carcasses are broken down into `MeatCut`s, `Offal`, and `ByProduct`s.
3.  **Storage Management:** All inventory items (`Carcass`, `MeatCut`, `Offal`, `ByProduct`) are assigned to and tracked within `StorageLocation`s.
4.  **Disposition Tracking:** The final disposition of each item (e.g., 'returned_to_owner', 'for_sale', 'disposed') is managed.
5.  **Labeling & Traceability:** Integration with the `labeling` app for physical labels and maintaining traceability from the original `Animal`.

## 4. Key Functionalities

*   **Carcass Management:** Creation, status tracking (chilling, disassembly ready, frozen, dispatched), and disposition.
*   **Product Disassembly:** Breaking down carcasses into various cuts and by-products.
*   **Storage Location Management:** Assigning and tracking inventory items in specific physical locations.
*   **Inventory Movement:** Recording transfers of items between storage locations.
*   **Disposition Updates:** Changing the intended use or fate of inventory items.
*   **Label Assignment:** Associating physical labels (e.g., barcode IDs) with inventory items.
*   **Traceability Queries:** Providing mechanisms to trace all derived products back to the original animal, or to find all items in a given location.