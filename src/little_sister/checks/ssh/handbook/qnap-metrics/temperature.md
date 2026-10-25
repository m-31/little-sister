# Temperature

The NAS's temperatures in °C, as QTS's `getsysinfo` reads them: the system's and the
processor's where the model has those sensors, and each drive's, a node a populated bay,
with its bay among its details.

## How to read it

One pair of levels holds for every sensor alike: above 50 °C a warning and above 60 °C
an error, by default; the node's *Configuration* says the levels it was graded by. A
processor runs hotter than the rest of the NAS, so it may warn first at a heat that is
normal for it. A drive's maker gives the highest temperature it is made to run at on its
data sheet, and a drive runs longest well below it.

## When it runs hot

1. Look at the fans: a fan that stopped, or runs slow, is the usual cause. QTS's
   system status shows their speed.
2. Look at the air: dust in the intake, a NAS in a closed cupboard, against a wall or
   beside something warm, a room that grew warmer.
3. A drive that runs hotter than its neighbours may be failing: its SMART verdict
   stands beside this.
4. {error}: cool it now — open the cupboard, move the air — or shut the NAS down until
   it can be cooled. Heat shortens a drive's life, and a NAS may be set to shut itself
   down when it runs too hot.

## Its levels

`max_temperature_warn` and `max_temperature_error`, in °C, in the check's file, each the
last temperature that passes. Write the pair whole: a level the file leaves out is not
compared. They hold for the system, the processor and every drive alike;
`max_temperature: null` reads the temperatures without grading them.
