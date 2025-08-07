# App: inventory

## Purpose
Manages the final stage of the process: labeling the carcass and tracking it in the depot or warehouse.

## Core Models

- **Carcass**:
  - `animal`: (OneToOneField to `processing.Animal`)
  - `net_weight`: (DecimalField, from the final WeightLog)
  - `storage_location`: (CharField)
  - `is_released`: (BooleanField)
- **Label**:
  - `carcass`: (ForeignKey to `Carcass`)
  - `qr_code`: (ImageField, generated)
  - `print_date`: (DateTimeField)

## Key Logic
- A view triggered after carcass weighing to generate a `Carcass` record.
- A function to generate a QR code containing key animal and weight data.
- A print view for the label.
- An interface to manage `storage_location` and mark carcasses as `released` to the client.