# Inventory App – Design Plan

This document defines the high-level architecture, core concepts, and business workflow of the `inventory` app within the Slaughterhouse Management System.

## 1. App Architecture Overview

| App Name | Responsibility |
| :--- | :--- |
| `inventory` | Manages post-slaughter assets, packaging, storage, and disposition. |

## Design Q&A Session

### 1. **Transition from Processing to Inventory**
**Q:** When an animal reaches `carcass_ready` status, should it automatically create a `Carcass` record in inventory?  
**A:** Yes, it should create a record for carcass ready chilling automatically.

**Q:** Should the animal status remain `carcass_ready` in processing while also existing in inventory?  
**A:** Yes, animal status remains in `carcass_ready` after 1 day chilling process. Depends on the service, we are going to update the status of processing app.

### 2. **Weight Data Handling**
**Q:** Should inventory copy the final weights, or reference them from processing?  
**A:** Inventory system can use the processing app WeightLog system because it handles most of the cases.

**Q:** Do we need separate weight tracking in inventory for post-processing changes?  
**A:** TBD for separate weight tracking.

### 3. **QR Code System Design**
**Q:** What specific actions should clerks be able to perform via QR code?  
**A:** QR code actions include:
- Assign to storage location
- Change status (ready for disassembly, dispatched, etc.)
- Record movements between locations
- Update disposition (returned to owner, for sale, etc.)

**Q:** Should the QR code be printable directly from the processing app or only after inventory intake?  
**A:** For printing QR code, we have an app called `labeling` - all print jobs use that app.

### 4. **Storage Location Management**
**Q:** How granular should location tracking be?  
**A:** Storage location going to be basic - no rack or anything, just storage name.

**Q:** Should capacity be by count or by weight?  
**A:** Both count and weight capacity tracking.

### 5. **Real-time Updates**
**Q:** What type of real-time updates needed?  
**A:** Real-time updates would be good. Volume is not that high - max 100 users going to use the app.

### 6. **Dashboard Priorities**
**Q:** What metrics should be displayed?  
**A:** Metrics should be:
- Storage capacities
- Total inventory count
- Pending actions after chilling process

## 7. **Inventory App Logic & Workflow**

### Automatic Carcass Creation Process
1. **Trigger Event**: When an animal in processing app reaches `carcass_ready` status
2. **Auto-Creation**: System automatically creates a `Carcass` record in inventory app
3. **Status Management**: Animal remains `carcass_ready` in processing app during 1-day chilling
4. **Chilling Period**: After chilling completion, processing app status may be updated based on service package

### Weight Integration Strategy
- **Primary Source**: Use processing app's `WeightLog` system as the authoritative weight source
- **Reference Method**: Inventory app references weights rather than duplicating data
- **Future Consideration**: Separate weight tracking in inventory is TBD and will be evaluated based on operational needs

### QR Code Integration Workflow
1. **Generation**: QR codes generated for each carcass upon creation in inventory
2. **Print Management**: All QR code printing handled through the `labeling` app
3. **Clerk Actions via QR Code**:
   - **Storage Assignment**: Scan to assign carcass to specific storage location
   - **Status Updates**: Change status (chilling → disassembly_ready → frozen → dispatched)
   - **Movement Tracking**: Record transfers between storage locations
   - **Disposition Updates**: Update final disposition (returned_to_owner, for_sale, disposed)
4. **Mobile Interface**: QR code interface optimized for clerk mobile devices/tablets

### Storage Location Management
- **Simplicity**: Basic storage location tracking (storage name only)
- **No Complex Hierarchy**: No rack, shelf, or detailed positioning
- **Dual Capacity Tracking**:
  - **Count Capacity**: Maximum number of items per location
  - **Weight Capacity**: Maximum weight capacity per location
- **Real-time Utilization**: Track current count and weight vs. capacity

### Real-time Dashboard Features
- **User Scale**: Designed for max 100 concurrent users
- **Key Metrics Display**:
  - **Storage Utilization**: Current vs. capacity (both count and weight)
  - **Total Inventory Count**: Active carcasses in system
  - **Pending Actions**: Animals awaiting intake from processing
  - **Chilling Status**: Items in various stages of chilling process
- **Auto-refresh**: Periodic updates for real-time data display

### Integration Points
1. **Processing App**: 
   - Listen for `carcass_ready` status changes
   - Reference `WeightLog` data
   - Coordinate status updates after chilling
2. **Labeling App**:
   - Send QR code print requests
   - Manage label lifecycle
3. **Future Apps**: Prepared for integration with sales, dispatch, and customer management systems

## 2. Key Entities / Concepts

*   **`Carcass`**: Represents the whole body of a slaughtered animal after initial processing.
*   **`MeatCut`**: Individual portions of meat derived from a `Carcass`.
*   **`Offal`**: Edible or inedible organs and entrails from a slaughtered animal.
*   **`ByProduct`**: Other valuable products derived from the animal (e.g., skin, head, feet).
*   **`StorageLocation`**: Defines physical locations within the facility where inventory items are stored (e.g., freezers, coolers).

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