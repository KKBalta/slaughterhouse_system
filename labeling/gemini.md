# Labeling App – Design Plan

This document outlines the design and functionality of the `labeling` app within the Slaughterhouse Management System. The primary responsibility of this app is to generate and manage various types of labels required throughout the animal processing workflow.

## 1. Project Principles (Specific to Labeling)

*   **Automation:** Maximize automated label generation and printing.
*   **Accuracy:** Ensure labels accurately reflect product information and compliance requirements.
*   **Integration:** Seamless integration with barcode/RFID systems and other apps.
*   **Flexibility:** Support various label formats and content based on product type and destination.

## 2. App Architecture Overview

| App Name | Responsibility | Key Entities / Concepts |
| :--- | :--- | :--- |
| `labeling` | Generates and prints labels for assets, integrated with barcode/RFID systems. | `Barcode`, `RFID`, `LabelTemplate` |

## 3. Key Functionalities

*   **Label Generation:** Create labels for:
    *   Individual animals (wristbands)
    *   Carcasses
    *   Meat cuts
    *   Offal and by-products
    *   Packaged products
    *   Shipping containers
*   **Template Management:** Define and manage various label templates to ensure consistency and compliance.
*   **Barcode/RFID Integration:** Generate and encode barcodes (e.g., EAN-13, QR codes) or RFID tags.
*   **Printing:** Interface with label printers for automated printing.
*   **History & Audit:** Maintain a history of generated labels for traceability and auditing purposes.

## 4. Enhanced Traceability: QR Code Wristbands

To further enhance traceability and client transparency, the `labeling` app will support the generation of QR code wristbands for individual animals.

*   **Purpose:** These wristbands will serve as a primary, scannable identifier for each animal throughout its processing journey. Scanning the QR code will provide real-time access to the animal's processing status and history.
*   **Generation:**
    *   A unique QR code will be generated for each `Animal` record created in the `processing` app, ideally at the point of reception/intake.
    *   The QR code will encode a unique URL (e.g., `https://yourdomain.com/portal/track_animal/<animal_id>/`). The `<animal_id>` will typically be the `Animal`'s primary key (`pk`) or a stable `identification_tag`.
    *   The `labeling` app will manage the generation of the QR code image and its association with the specific `Animal` record.
*   **Integration with Portal App:**
    *   The encoded URL will direct users to a dedicated page within the `portal` app.
    *   This `portal` page will dynamically retrieve and display the animal's current processing status (e.g., `received`, `slaughtered`, `disassembled`, `packaged`), along with relevant historical data (e.g., weight logs, dates of key transitions).
    *   This provides a read-only, real-time view of the animal's progress, enhancing transparency for clients and internal tracking.
*   **Physical Implementation:** The QR codes will be printed on durable, animal-friendly wristbands designed to withstand the conditions of the slaughterhouse environment.
