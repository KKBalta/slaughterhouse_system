# IoT Scale Integration Plan
## Slaughterhouse Management System

**Date:** 2025-01-27  
**Purpose:** Integrate RS232 scale device for real-time weight data in disassembly module

---

## Executive Summary

This document outlines the architecture and implementation plan for integrating an RS232 scale device into the slaughterhouse management system. The goal is to enable real-time weight polling from the scale during disassembly operations while minimizing on-site devices and wiring complexity.

---

## Architecture Decision: Direct Integration vs Microservice

### Recommended Approach: **Hybrid Edge Gateway**

After analyzing your requirements:
- ✅ Minimize devices on site
- ✅ Minimize wiring
- ✅ Real-time data polling
- ✅ Cloud instance integration

**Recommended Solution:** Lightweight Edge Gateway Device

#### Architecture Overview

```
┌─────────────────┐
│  RS232 Scale    │
│  (On-site)      │
└────────┬────────┘
         │ RS232 Serial
         │
┌────────▼─────────────────────────────┐
│  Edge Gateway Device                 │
│  (Raspberry Pi / Small PC)          │
│  - Reads RS232                       │
│  - Converts to HTTP/WebSocket        │
│  - Sends to Cloud via WiFi/Ethernet  │
└────────┬─────────────────────────────┘
         │ HTTPS/WebSocket
         │
┌────────▼─────────────────────────────┐
│  Django Cloud Instance              │
│  - Receives weight data              │
│  - Stores in database               │
│  - Provides real-time API           │
└─────────────────────────────────────┘
```

### Why This Approach?

1. **Minimal On-Site Hardware:**
   - Single small device (Raspberry Pi 4 or similar) - ~$50-100
   - Connects to scale via RS232 (standard serial cable)
   - Uses existing WiFi/Ethernet infrastructure
   - No additional wiring beyond scale connection

2. **Separation of Concerns:**
   - Edge device handles low-level RS232 communication
   - Cloud handles business logic, database, user interface
   - Easy to maintain and update independently

3. **Reliability:**
   - Edge device can buffer data if network is temporarily down
   - Can retry failed transmissions
   - Cloud instance doesn't need direct hardware access

4. **Scalability:**
   - Easy to add more scales in the future
   - Each scale gets its own edge gateway
   - Cloud can handle multiple scales simultaneously

---

## Alternative Approaches (Not Recommended)

### ❌ Direct RS232 to Cloud
**Why not:** Cloud instances typically don't have direct hardware access. Would require:
- VPN tunnel to on-site computer
- Complex network configuration
- Security concerns
- Difficult to maintain

### ❌ Full Microservice
**Why not:** Overkill for this use case. Would require:
- Separate deployment infrastructure
- More complex monitoring
- Higher operational overhead
- Unnecessary for single scale integration

---

## Technical Implementation Plan

### Phase 1: Edge Gateway Device (Python)

**Location:** Separate repository or module  
**Technology:** Python with `pyserial` and `requests`/`websocket-client`

**Responsibilities:**
1. Open RS232 connection to scale
2. Poll scale at configurable interval (e.g., every 100ms)
3. Parse scale data format
4. Send data to cloud via HTTP POST or WebSocket
5. Handle connection errors and retries
6. Local logging for debugging

**Key Features:**
- Configurable scale protocol (different scales use different formats)
- Automatic reconnection on failure
- Data validation before sending
- Heartbeat/health check mechanism

### Phase 2: Django Cloud Integration

**Location:** New Django app `iot` or extend `processing` app

**Components:**

#### 2.1 API Endpoint for Receiving Weight Data
- REST endpoint: `POST /api/iot/scale/reading/`
- Authentication: API key or JWT token
- Validates incoming data
- Stores in database

#### 2.2 Real-time Weight Data Model
```python
class ScaleReading(BaseModel):
    scale_id = models.CharField(max_length=100)  # Identifier for the scale
    weight_kg = models.DecimalField(max_digits=10, decimal_places=3)
    timestamp = models.DateTimeField(auto_now_add=True)
    is_stable = models.BooleanField(default=False)  # Weight stabilized
    animal = models.ForeignKey(Animal, null=True, blank=True)  # If associated
    session_id = models.CharField(max_length=100, null=True)  # Current weighing session
```

#### 2.3 WebSocket/SSE for Real-time Updates
- WebSocket endpoint for disassembly view
- Pushes latest weight reading to connected clients
- Updates UI in real-time without polling

#### 2.4 Integration with Disassembly Module
- Modify `DisassemblyCutForm` to show real-time weight
- Auto-populate weight field from scale
- User confirms/edits weight before saving

---

## Detailed Implementation

### Edge Gateway Code Structure

```
edge_gateway/
├── config.yaml          # Scale configuration
├── main.py              # Main entry point
├── scale_reader.py      # RS232 reading logic
├── data_sender.py      # HTTP/WebSocket sender
├── logger.py           # Logging setup
└── requirements.txt    # Python dependencies
```

### Django Integration Structure

```
iot/                    # New Django app
├── models.py           # ScaleReading model
├── views.py            # API endpoints
├── serializers.py      # DRF serializers (if using DRF)
├── consumers.py        # WebSocket consumers (if using Channels)
└── urls.py             # URL routing

processing/
├── views.py            # Modified disassembly views
└── templates/
    └── processing/
        └── disassembly_detail.html  # Updated with real-time weight
```

---

## Data Flow

### Real-time Weight Reading Flow

1. **Scale → Edge Gateway:**
   - Edge device polls scale via RS232
   - Receives weight reading (e.g., "125.5 kg")
   - Parses and validates data

2. **Edge Gateway → Cloud:**
   - Sends HTTP POST to `/api/iot/scale/reading/`
   - Includes: `scale_id`, `weight_kg`, `timestamp`, `is_stable`

3. **Cloud → Database:**
   - Django receives POST request
   - Validates and stores `ScaleReading`
   - Associates with current disassembly session if applicable

4. **Cloud → Frontend:**
   - WebSocket/SSE pushes update to connected clients
   - Disassembly view receives latest weight
   - UI updates weight field in real-time

5. **User Action:**
   - User sees real-time weight in disassembly form
   - User confirms weight (or edits if needed)
   - User saves disassembly cut with confirmed weight

---

## Configuration

### Edge Gateway Configuration (`config.yaml`)

```yaml
scale:
  port: "/dev/ttyUSB0"  # or "COM3" on Windows
  baudrate: 9600
  timeout: 1.0
  protocol: "mettler_toledo"  # or "sartorius", "custom", etc.

cloud:
  api_url: "https://your-cloud-instance.com/api/iot/scale/reading/"
  api_key: "your-secret-api-key"
  retry_attempts: 3
  retry_delay: 5  # seconds

polling:
  interval_ms: 100  # Poll every 100ms
  stable_threshold: 0.1  # Weight change < 0.1kg = stable
  stable_duration_ms: 500  # Must be stable for 500ms
```

### Django Settings

```python
# config/settings.py
IOT_SCALE_CONFIG = {
    'API_KEY': config('IOT_SCALE_API_KEY'),
    'ALLOWED_SCALE_IDS': config('IOT_SCALE_IDS', cast=Csv()),
    'WEIGHT_STABLE_THRESHOLD': 0.1,  # kg
    'WEIGHT_STABLE_DURATION': 0.5,  # seconds
}
```

---

## Security Considerations

1. **API Authentication:**
   - Use API keys for edge gateway authentication
   - Rotate keys periodically
   - Store keys securely (environment variables)

2. **Network Security:**
   - Use HTTPS for all communications
   - Consider VPN for additional security
   - Firewall rules to restrict access

3. **Data Validation:**
   - Validate weight ranges (e.g., 0-1000 kg)
   - Rate limiting on API endpoints
   - Sanitize all inputs

---

## Deployment Steps

### Step 1: Set Up Edge Gateway Device

1. Install Raspberry Pi OS or similar
2. Install Python 3.9+
3. Install dependencies: `pip install pyserial requests`
4. Configure `config.yaml` with scale and cloud settings
5. Set up as systemd service for auto-start
6. Test connection to scale and cloud

### Step 2: Django Cloud Integration

1. Create `iot` Django app
2. Add `ScaleReading` model
3. Create API endpoint for receiving data
4. Add WebSocket/SSE support (optional but recommended)
5. Update disassembly views and templates
6. Deploy to cloud instance

### Step 3: Integration Testing

1. Test RS232 communication
2. Test cloud API endpoint
3. Test real-time updates in disassembly view
4. Test error handling and reconnection

---

## Cost Estimation

### Hardware
- Raspberry Pi 4 (4GB): ~$75
- RS232 to USB adapter: ~$10
- SD Card (32GB): ~$10
- Power supply: ~$10
- **Total: ~$105**

### Software Development
- Edge gateway development: 2-3 days
- Django integration: 2-3 days
- Testing and deployment: 1-2 days
- **Total: 5-8 days**

### Ongoing Maintenance
- Minimal: Edge device runs autonomously
- Cloud monitoring: Included in existing infrastructure
- Updates: As needed for scale protocol changes

---

## Future Enhancements

1. **Multiple Scales:**
   - Support multiple scales with different `scale_id`
   - Dashboard showing all active scales
   - Scale status monitoring

2. **Advanced Features:**
   - Weight history and trends
   - Automatic cut weight suggestions based on hot carcass weight
   - Integration with barcode scanner for automatic animal association

3. **Analytics:**
   - Average weights by animal type
   - Disassembly efficiency metrics
   - Weight loss tracking (hot → cold → final)

---

## Next Steps

1. **Confirm Scale Model:**
   - Identify exact scale model and protocol
   - Obtain scale documentation/manual
   - Test RS232 communication locally

2. **Prototype Edge Gateway:**
   - Build basic RS232 reader
   - Test with actual scale
   - Verify data format

3. **Implement Django Integration:**
   - Create `iot` app
   - Build API endpoint
   - Integrate with disassembly module

4. **Deploy and Test:**
   - Deploy edge gateway to on-site device
   - Deploy Django changes to cloud
   - End-to-end testing

---

## Questions to Resolve

1. **Scale Model:** What is the exact model of the scale? (needed for protocol implementation)
2. **Scale Protocol:** Does the scale have documentation for RS232 communication?
3. **Network:** Is WiFi available at the scale location, or do we need Ethernet?
4. **Power:** Is power available for the edge gateway device?
5. **Location:** Where will the edge gateway device be physically located?
6. **Multiple Scales:** Will there be multiple scales in the future?

---

## Conclusion

The **Hybrid Edge Gateway** approach provides the best balance of:
- ✅ Minimal on-site hardware
- ✅ Minimal wiring
- ✅ Real-time data flow
- ✅ Scalability
- ✅ Maintainability
- ✅ Cost-effectiveness

This architecture allows for easy expansion to multiple scales and provides a solid foundation for future IoT integrations.


