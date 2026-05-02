
--- PyMuPDF page 88 ---

EVB-88
< DTC/CIRCUIT DIAGNOSIS >
P0A0D HV SYSTEM INTERLOCK ERROR
DTC/CIRCUIT DIAGNOSIS
P0A0D HV SYSTEM INTERLOCK ERROR
DTC Logic
INFOID:0000000008745933
DTC DETECTION LOGIC
DTC CONFIRMATION PROCEDURE
1.PERFORM DTC CONFIRMATION PROCEDURE
With CONSULT
1.
Power switch ON and wait for 10 seconds or more.
2.
Select “Self Diagnostic Result” of “HV BAT”.
3.
Check DTC.
Is P0A1F detected?
YES
>> Refer to EVB-88, "Diagnosis Procedure".
NO
>> INSPECTION END
Diagnosis Procedure
INFOID:0000000009346499
DANGER:
Since hybrid vehicles and electric vehicles contain a high voltage battery, there is the risk of
electric shock, electric leakage, or similar accidents if the high voltage component and vehicle are
handled incorrectly. Be sure to follow the correct work procedures when performing inspection and
maintenance.
WARNING:
• Be sure to remove the service plug in order to disconnect the high voltage circuits before perform-
ing inspection or maintenance of high voltage system harnesses and parts.
• The removed service plug must always be carried in a pocket of the responsible worker or placed in
the tool box during the procedure to prevent the plug from being connected by mistake.
• Be sure to wear insulating protective equipment consisting of glove, shoes, face shield and glasses
before beginning work on the high voltage system.
• Never allow workers other than the responsible person to touch the vehicle containing high voltage
parts. To keep others from touching the high voltage parts, these parts must be covered with an insu-
lating sheet except when using them.
• Refer to EVB-6, "High Voltage Precautions".
CAUTION:
Never bring the vehicle into the READY status with the service plug removed unless otherwise
instructed in the Service Manual. A malfunction may occur if this is not observed.
1.PRECONDITIONING
WARNING:
Disconnect the high voltage. Refer to GI-33, "How to Disconnect High Voltage".
1.
Remove Li-ion battery. Refer to EVB-194, "Removal and Installation".
2.
Remove battery pack upper case. Refer to EVB-204, "BATTERY PACK UPPER CASE : Removal and
Installation".
>> GO TO 2.
2.CHECK LI-ION BATTERY INTERLOCK DETECTIONG CIRCUIT FOR SHORT-1
1.
Disconnect Li-ion battery controller (LBC) harness connector.
2.
Disconnect interlock detecting switch (high voltage harness connector) harness connector.
3.
Check the continuity between Li-ion battery controller harness connector and ground.
DTC
Trouble diagnosis name
DTC detecting condition
Possible causes
P0A0D
HV SYSTEM INTERLOCK 
ERROR
Self diagnosis program of Li-ion battery controller de-
tects a malfunction in the CPU.
Li-ion battery controller
Revision: October 2013
2013 LEAF

--- PyMuPDF page 89 ---

P0A0D HV SYSTEM INTERLOCK ERROR
EVB-89
< DTC/CIRCUIT DIAGNOSIS >
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
A
B
EVB
N
O
P
Is the inspection result normal?
YES
>> GO TO 3.
NO
>> Replace Li-ion battery vehicle communication harness.
3.CHECK LI-ION BATTERY INTERLOCK DETECTIONG CIRCUIT FOR SHORT-2
1.
Disconnect interlock detecting switch (service plug) harness connector.
2.
Check the continuity between Li-ion battery controller harness connector and ground.
Is the inspection result normal?
YES
>> GO TO 4.
NO
>> Replace Li-ion battery vehicle communication harness.
4.CHECK INTERLOCK DETECTIONG SWITCH (SERVICE PLUG)
Refer to EVB-89, "Component Inspection".
Is the inspection result normal?
YES
>> Replace Li-ion battery controller. Refer to EVB-214, "LI-ION BATTERY CONTROLLER : Removal
and Installation".
NO
>> Replace service plug.
Component Inspection
INFOID:0000000009346500
1.CHECK INTERLOCK DETECTIONG SWITCH (SERVICE PLUG)
Check the continuity between terminals in the figure.
Is the inspection result normal?
YES
>> INSPECTION END
NO
>> Replace service plug.
LBC
—
Continuity
Connector
Terminal
LB11
8
Ground
Not existed
LBC
—
Continuity
Connector
Terminal
LB11
6
Ground
Not existed
Value:
Approx. 0 Ω
JPCIA0347ZZ
Revision: October 2013
2013 LEAF

--- PyMuPDF page 90 ---

EVB-90
< DTC/CIRCUIT DIAGNOSIS >
P0A1F BATTERY ENERGY CONTROL MODULE
P0A1F BATTERY ENERGY CONTROL MODULE
DTC Logic
INFOID:0000000008745935
DTC DETECTION LOGIC
DTC CONFIRMATION PROCEDURE
1.PERFORM DTC CONFIRMATION PROCEDURE
With CONSULT
1.
Power switch ON and wait for 10 seconds or more.
2.
Select “Self Diagnostic Result” of “HV BAT”.
3.
Check DTC.
Is P0A1F detected?
YES
>> Refer to EVB-90, "Diagnosis Procedure".
NO
>> INSPECTION END
Diagnosis Procedure
INFOID:0000000008745936
When this DTC is detected, replace Li-ion battery controller. Refer to EVB-214, "LI-ION BATTERY CONTROL-
LER : Removal and Installation".
DTC
Trouble diagnosis name
DTC detecting condition
Possible causes
P0A1F
BATTERY ENERGY CON-
TROL MODULE
Self diagnosis program of Li-ion battery controller de-
tects a malfunction in the CPU.
Li-ion battery controller
Revision: October 2013
2013 LEAF

--- PyMuPDF page 91 ---

P3030 CELL CONTROLLER LIN
EVB-91
< DTC/CIRCUIT DIAGNOSIS >
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
A
B
EVB
N
O
P
P3030 CELL CONTROLLER LIN
DTC Logic
INFOID:0000000008745937
DTC DETECTION LOGIC
DTC CONFIRMATION PROCEDURE
1.PERFORM DTC CONFIRMATION PROCEDURE
With CONSULT
1.
Power switch ON and wait for 10 seconds or more.
2.
Select “Self Diagnostic Result” of “HV BAT”.
3.
Check DTC.
Is P3030 detected?
YES
>> Refer to EVB-91, "Diagnosis Procedure".
NO
>> INSPECTION END
Diagnosis Procedure
INFOID:0000000008745938
1.PERFORM THE SELF-DIAGNOSIS OF LI-ION BATTERY CONTROLLER
With CONSULT
1.
Select “Self Diagnostic Result” of “HV BAT”.
2.
Check to see if “P3375 - P33A4” is detected simultaneously with “P3030”.
Is P30F3 detected?
YES
>> • When “P3375” - “P3380” are detected simultaneously, perform the diagnosis procedure of
“P3375” - “P3380”. Refer to EVB-135, "Diagnosis Procedure".
• When “P3381” - “P338C” are detected simultaneously, perform the diagnosis procedure of
“P3381” - “P338C”. Refer to EVB-139, "Diagnosis Procedure".
• When “P338D” - “P3398” are detected simultaneously, perform the diagnosis procedure of
“P338D” - “P3398”. Refer to EVB-143, "Diagnosis Procedure".
• When “P3399” - “P33A4” are detected simultaneously, perform the diagnosis procedure of
“P3399” - “P33A4”. Refer to EVB-146, "Diagnosis Procedure".
NO
>> Replace Li-ion battery controller. Refer to EVB-214, "LI-ION BATTERY CONTROLLER : Removal
and Installation".
DTC
Trouble diagnosis name
DTC detecting condition
Possible causes
P3030
CELL CONT LIN
A malfunction occurs with the communication function in 
Li-ion battery controller.
• Li-ion battery controller
• Module
• Harness or connector
Revision: October 2013
2013 LEAF

--- PyMuPDF page 92 ---

EVB-92
< DTC/CIRCUIT DIAGNOSIS >
P3031-P303C CELL CONTROLLER ASIC
P3031-P303C CELL CONTROLLER ASIC
DTC Logic
INFOID:0000000008745939
DTC DETECTION LOGIC
DTC CONFIRMATION PROCEDURE
1.PERFORM DTC CONFIRMATION PROCEDURE
With CONSULT
1.
Power switch ON and wait for 10 seconds or more.
2.
Select “Self Diagnostic Result” of “HV BAT”.
3.
Check DTC.
Is any DTC detected?
YES
>> Refer to EVB-92, "Diagnosis Procedure".
NO
>> INSPECTION END
Diagnosis Procedure
INFOID:0000000008745940
1.PERFORM THE SELF-DIAGNOSIS OF LI-ION BATTERY CONTROLLER
With CONSULT
1.
Select “Self Diagnostic Result” of “HV BAT”.
2.
Check to see if “P3030” is detected simultaneously with “P3031 -P303C”.
Is P3030 detected?
YES
>> Perform diagnosis on the detected P3030. Refer to EVB-91, "Diagnosis Procedure".
NO
>> Replace Li-ion battery controller. Refer to EVB-214, "LI-ION BATTERY CONTROLLER : Removal
and Installation".
DTC
Trouble diagnosis name
DTC detecting condition
Possible causes
P3031
CELL CONT ASIC1
A malfunction occurs with the communication function 
in Li-ion battery controller.
Li-ion battery controller
P3032
CELL CONT ASIC2
P3033
CELL CONT ASIC3
P3034
CELL CONT ASIC4
P3035
CELL CONT ASIC5
P3036
CELL CONT ASIC6
P3037
CELL CONT ASIC7
P3038
CELL CONT ASIC8
P3039
CELL CONT ASIC9
P303A
CELL CONT ASIC10
P303B
CELL CONT ASIC11
P303C
CELL CONT ASIC12
Revision: October 2013
2013 LEAF