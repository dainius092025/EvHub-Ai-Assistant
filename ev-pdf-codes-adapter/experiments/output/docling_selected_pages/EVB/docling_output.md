

<!-- Docling: pages 88–92 -->

## P0A0D HV SYSTEM INTERLOCK ERROR

## &lt; DTC/CIRCUIT DIAGNOSIS &gt;

## DTC/CIRCUIT DIAGNOSIS

## P0A0D HV SYSTEM INTERLOCK ERROR

DTC Logic

## DTC DETECTION LOGIC

| DTC   | Trouble diagnosis name    | DTC detecting condition                                                                 | Possible causes           |
|-------|---------------------------|-----------------------------------------------------------------------------------------|---------------------------|
| P0A0D | HV SYSTEM INTERLOCK ERROR | Self diagnosis program of Li-ion battery controller de- tects a malfunction in the CPU. | Li-ion battery controller |

## DTC CONFIRMATION PROCEDURE

## 1.PERFORM DTC CONFIRMATION PROCEDURE

## With CONSULT

1. Power switch ON and wait for 10 seconds or more.
2. Select 'Self Diagnostic Result' of 'HV BAT'.
3. Check DTC.

## Is P0A1F detected?

YES &gt;&gt; Refer to EVB-88, "Diagnosis Procedure".

NO &gt;&gt; INSPECTION END

## Diagnosis Procedure

## DANGER:

<!-- image -->

Since hybrid vehicles and electric vehicles contain a high voltage battery, there is the risk of electric shock, electric leakage, or similar accidents if the high voltage component and vehicle are handled incorrectly. Be sure to follow the correct work procedures when performing inspection and maintenance.

## WARNING:

- Be sure to remove the service plug in order to disconnect the high voltage circuits before performing inspection or maintenance of high voltage system harnesses and parts.
- The removed service plug must always be carried in a pocket of the responsible worker or placed in the tool box during the procedure to prevent the plug from being connected by mistake.
- Be sure to wear insulating protective equipment consisting of glove, shoes, face shield and glasses before beginning work on the high voltage system.
- Never allow workers other than the responsible person to touch the vehicle containing high voltage parts. To keep others from touching the high voltage parts, these parts must be covered with an insulating sheet except when using them.
- Refer to EVB-6, "High Voltage Precautions".

## CAUTION:

Never  bring  the  vehicle  into  the  READY  status  with  the  service  plug  removed  unless  otherwise instructed in the Service Manual. A malfunction may occur if this is not observed.

## 1.PRECONDITIONING

## WARNING:

## Disconnect the high voltage. Refer to GI-33, "How to Disconnect High Voltage".

1. Remove Li-ion battery. Refer to EVB-194, "Removal and Installation".
2. Remove battery pack upper case. Refer to EVB-204, "BATTERY PACK UPPER CASE : Removal and Installation".

&gt;&gt; GO TO 2.

## 2.CHECK LI-ION BATTERY INTERLOCK DETECTIONG CIRCUIT FOR SHORT-1

1. Disconnect Li-ion battery controller (LBC) harness connector.
2. Disconnect interlock detecting switch (high voltage harness connector) harness connector.
3. Check the continuity between Li-ion battery controller harness connector and ground.

INFOID:0000000008745933

INFOID:0000000009346499

## P0A0D HV SYSTEM INTERLOCK ERROR

## &lt; DTC/CIRCUIT DIAGNOSIS &gt;

| LBC       | LBC      | -      | Continuity   |
|-----------|----------|--------|--------------|
| Connector | Terminal |        |              |
| LB11      | 8        | Ground | Not existed  |

## Is the inspection result normal?

YES &gt;&gt; GO TO 3.

- NO &gt;&gt; Replace Li-ion battery vehicle communication harness.
- 3.CHECK LI-ION BATTERY INTERLOCK DETECTIONG CIRCUIT FOR SHORT-2
1. Disconnect interlock detecting switch (service plug) harness connector.
2. Check the continuity between Li-ion battery controller harness connector and ground.

| LBC       | LBC      | -      | Continuity   |
|-----------|----------|--------|--------------|
| Connector | Terminal | -      | Continuity   |
| LB11      | 6        | Ground | Not existed  |

## Is the inspection result normal?

YES &gt;&gt; GO TO 4.

- NO &gt;&gt; Replace Li-ion battery vehicle communication harness.
- 4.CHECK INTERLOCK DETECTIONG SWITCH (SERVICE PLUG)

## Refer to EVB-89, "Component Inspection".

## Is the inspection result normal?

- YES &gt;&gt; Replace Li-ion battery controller. Refer to EVB-214, "LI-ION BATTERY CONTROLLER : Removal and Installation".
- NO &gt;&gt; Replace service plug.

## Component Inspection

- 1.CHECK INTERLOCK DETECTIONG SWITCH (SERVICE PLUG)

Check the continuity between terminals in the figure.

Value: Approx. 0 Ω

## Is the inspection result normal?

YES &gt;&gt; INSPECTION END

NO &gt;&gt; Replace service plug.

INFOID:0000000009346500

<!-- image -->

A

B

EVB

D

E

F

G

H

I

J

K

L

M

N

O

P

## P0A1F BATTERY ENERGY CONTROL MODULE

## &lt; DTC/CIRCUIT DIAGNOSIS &gt;

## P0A1F BATTERY ENERGY CONTROL MODULE

## DTC Logic

## DTC DETECTION LOGIC

| DTC   | Trouble diagnosis name          | DTC detecting condition                                                                 | Possible causes           |
|-------|---------------------------------|-----------------------------------------------------------------------------------------|---------------------------|
| P0A1F | BATTERY ENERGY CON- TROL MODULE | Self diagnosis program of Li-ion battery controller de- tects a malfunction in the CPU. | Li-ion battery controller |

## DTC CONFIRMATION PROCEDURE

## 1.PERFORM DTC CONFIRMATION PROCEDURE

## With CONSULT

1. Power switch ON and wait for 10 seconds or more.
2. Select 'Self Diagnostic Result' of 'HV BAT'.
3. Check DTC.

## Is P0A1F detected?

YES &gt;&gt; Refer to EVB-90, "Diagnosis Procedure".

NO &gt;&gt; INSPECTION END

## Diagnosis Procedure

INFOID:0000000008745936

When this DTC is detected, replace Li-ion battery controller. Refer to EVB-214, "LI-ION BATTERY CONTROLLER : Removal and Installation".

INFOID:0000000008745935

## P3030 CELL CONTROLLER LIN

## &lt; DTC/CIRCUIT DIAGNOSIS &gt;

## P3030 CELL CONTROLLER LIN

## DTC Logic

## DTC DETECTION LOGIC

| DTC   | Trouble diagnosis name   | DTC detecting condition                                                            | Possible causes                                             |
|-------|--------------------------|------------------------------------------------------------------------------------|-------------------------------------------------------------|
| P3030 | CELL CONT LIN            | A malfunction occurs with the communication function in Li-ion battery controller. | • Li-ion battery controller • Module • Harness or connector |

## DTC CONFIRMATION PROCEDURE

## 1.PERFORM DTC CONFIRMATION PROCEDURE

## With CONSULT

1. Power switch ON and wait for 10 seconds or more.
2. Select 'Self Diagnostic Result' of 'HV BAT'.
3. Check DTC.

## Is P3030 detected?

YES &gt;&gt; Refer to EVB-91, "Diagnosis Procedure".

NO &gt;&gt; INSPECTION END

## Diagnosis Procedure

## 1.PERFORM THE SELF-DIAGNOSIS OF LI-ION BATTERY CONTROLLER

## With CONSULT

1. Select 'Self Diagnostic Result' of 'HV BAT'.
2. Check to see if 'P3375 - P33A4' is detected simultaneously with 'P3030'.

## Is P30F3 detected?

- YES &gt;&gt; · When  'P3375'  -  'P3380'  are  detected  simultaneously,  perform  the  diagnosis  procedure  of 'P3375' - 'P3380'. Refer to EVB-135, "Diagnosis Procedure".
- When  'P3381'  -  'P338C'  are  detected  simultaneously,  perform  the  diagnosis  procedure  of 'P3381' - 'P338C'. Refer to EVB-139, "Diagnosis Procedure".
- When  'P338D'  -  'P3398'  are  detected  simultaneously,  perform  the  diagnosis  procedure  of 'P338D' - 'P3398'. Refer to EVB-143, "Diagnosis Procedure".
- When  'P3399'  -  'P33A4'  are  detected  simultaneously,  perform  the  diagnosis  procedure  of 'P3399' - 'P33A4'. Refer to EVB-146, "Diagnosis Procedure".
- NO &gt;&gt; Replace Li-ion battery controller. Refer to EVB-214, "LI-ION BATTERY CONTROLLER : Removal and Installation".

INFOID:0000000008745937

INFOID:0000000008745938

A

B

EVB

D

E

F

G

H

I

J

K

L

M

N

O

P

## P3031-P303C CELL CONTROLLER ASIC

## &lt; DTC/CIRCUIT DIAGNOSIS &gt;

## P3031-P303C CELL CONTROLLER ASIC

## DTC Logic

## DTC DETECTION LOGIC

| DTC   | Trouble diagnosis name   | DTC detecting condition                                                            | Possible causes           |
|-------|--------------------------|------------------------------------------------------------------------------------|---------------------------|
| P3031 | CELL CONT ASIC1          | A malfunction occurs with the communication function in Li-ion battery controller. | Li-ion battery controller |
| P3032 | CELL CONT ASIC2          | A malfunction occurs with the communication function in Li-ion battery controller. | Li-ion battery controller |
| P3033 | CELL CONT ASIC3          | A malfunction occurs with the communication function in Li-ion battery controller. | Li-ion battery controller |
| P3034 | CELL CONT ASIC4          | A malfunction occurs with the communication function in Li-ion battery controller. | Li-ion battery controller |
| P3035 | CELL CONT ASIC5          | A malfunction occurs with the communication function in Li-ion battery controller. | Li-ion battery controller |
| P3036 | CELL CONT ASIC6          | A malfunction occurs with the communication function in Li-ion battery controller. | Li-ion battery controller |
| P3037 | CELL CONT ASIC7          | A malfunction occurs with the communication function in Li-ion battery controller. | Li-ion battery controller |
| P3038 | CELL CONT ASIC8          | A malfunction occurs with the communication function in Li-ion battery controller. | Li-ion battery controller |
| P3039 | CELL CONT ASIC9          | A malfunction occurs with the communication function in Li-ion battery controller. | Li-ion battery controller |
| P303A | CELL CONT ASIC10         | A malfunction occurs with the communication function in Li-ion battery controller. | Li-ion battery controller |
| P303B | CELL CONT ASIC11         | A malfunction occurs with the communication function in Li-ion battery controller. | Li-ion battery controller |
| P303C | CELL CONT ASIC12         | A malfunction occurs with the communication function in Li-ion battery controller. | Li-ion battery controller |

## DTC CONFIRMATION PROCEDURE

## 1.PERFORM DTC CONFIRMATION PROCEDURE

## With CONSULT

1. Power switch ON and wait for 10 seconds or more.
2. Select 'Self Diagnostic Result' of 'HV BAT'.
3. Check DTC.

## Is any DTC detected?

YES

&gt;&gt; Refer to EVB-92, "Diagnosis Procedure".

NO &gt;&gt; INSPECTION END

## Diagnosis Procedure

## 1.PERFORM THE SELF-DIAGNOSIS OF LI-ION BATTERY CONTROLLER

## With CONSULT

1. Select 'Self Diagnostic Result' of 'HV BAT'.
2. Check to see if 'P3030' is detected simultaneously with 'P3031 -P303C'.

## Is P3030 detected?

YES &gt;&gt; Perform diagnosis on the detected P3030. Refer to EVB-91, "Diagnosis Procedure".

- NO &gt;&gt; Replace Li-ion battery controller. Refer to EVB-214, "LI-ION BATTERY CONTROLLER : Removal and Installation".

INFOID:0000000008745939

INFOID:0000000008745940