# App: processing

## Purpose
Handles the core operational workflow of processing an individual animal from entry to the point where the carcass is ready for labeling.

## Core Models

- **Animal**:
  - `order`: (ForeignKey to `reception.SlaughterOrder`)
  - `animal_type`: (Choices: Sheep, Cattle, etc.)
  - `tag_number`: (CharField, unique identifier)
  - `status`: (Choices: AwaitingProcessing, Skinning, Weighing, ReadyForDepot)
  - `entry_photo`: (ImageField)
  - `passport_photo`: (ImageField)
- **WeightLog**:
  - `animal`: (ForeignKey to `Animal`)
  - `weight_type`: (Choices: Skin, Carcass)
  - `weight_kg`: (DecimalField)
  - `timestamp`: (DateTimeField)
  - `scale_photo`: (ImageField, optional)

## Key Logic
- A fast-entry form for Clerks to add multiple animals to a `SlaughterOrder`.
- Views for updating an animal's status.
- Forms for entering skin and carcass weights, creating `WeightLog` entries.