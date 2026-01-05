# Conductive Yarn Fabric Design for Surface EMG

## 1. Material Selection
To replace conventional wires and form effective sEMG electrodes, the conductive yarn must have:
- **Low Resistance**: < 10 Ω/cm for interconnects, < 100 Ω/sq for electrodes.
- **Biocompatibility**: Silver-plated nylon or stainless steel fibers are common. Avoid copper in direct skin contact due to oxidation and potential irritation.
- **Washability**: The material must withstand washing cycles without significant degradation of conductivity.

### Recommended Yarns:
- **Silver-plated Nylon**: Good conductivity, flexible, solderable (sometimes).
- **Stainless Steel**: Durable, higher resistance than silver, good for heating or high-stretch applications, but harder to solder.
- **Carbon-infused**: Higher resistance, often used for pressure sensors, generally not suitable for low-noise EMG signal transmission.

## 2. Fabric Structure (Knitting vs. Weaving)
For wearable EMG, **knitting** (specifically circular or flat knitting) is generally preferred over weaving due to elasticity and form-fitting properties, which ensure better skin contact for electrodes.

### Electrode Design (The "Pad")
- **Intarsia Knitting**: Isolate the conductive yarn region (the electrode) within the non-conductive base fabric. This prevents short circuits.
- **Float Loops / Terry Loop**: Creating loops on the skin-facing side increases the surface area and contact pressure, improving signal quality.
- **Size**: Typically 10mm - 20mm diameter for sEMG to pick up specific muscle groups without too much crosstalk.

### Interconnects (The "Wire")
- **Plating/Inlay**: Run the conductive yarn as a specific course or wale to connect the electrode to the connector site.
- **Insulation**: The conductive path must be insulated from the skin (except at the electrode) and from the outside. Use a double-layer knit or cover the conductive trace with a non-conductive yarn (e.g., polyester, nylon) on both faces.

## 3. Noise Reduction & Signal Integrity
- **Shielding**: Ideally, sandwich the signal trace between ground planes (conductive fabric layers connected to GND) to reduce 50/60Hz hum, though this adds bulk.
- **Twisted Pair Equivalent**: If possible in the knitting structure, run a ground trace parallel to the signal trace to form a pseudo-differential pair structure.
- **Active Shielding**: If the electronics allow, drive a shield trace with the common-mode voltage.

## 4. Connection to Electronics (The "Hard-Soft" Interface)
This is the most common failure point.
- **Snap Buttons**: Standard ECG snaps crimped onto the fabric. Robust and easy to use.
- **Conductive Epoxy/Glue**: Flexible conductive glue can bond the yarn to a PCB pad.
- **Sewable PCBs**: PCBs with large plated holes for sewing conductive thread.
- **Magnetic Connectors**: increasing popularity for wearables (e.g., pogo pins).

## 5. Prototype Plan
1. **Sourcing**: Acquire silver-plated nylon yarn (e.g., 70D-200D).
2. **Swatch Testing**: Knit 3x3cm test patches to measure resistance per cm and contact impedance with skin.
3. **Integration**: Create a sleeve with 2 differential electrodes and 1 reference electrode (ground).
4. **Validation**: Compare signal SNR against standard Ag/AgCl gel electrodes.
