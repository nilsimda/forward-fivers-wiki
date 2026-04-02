---
layout: "../../layouts/DocsLayout.astro"
title: "Carve Data"
author: "Nils Imdahl"
---

To extract monster carve data in a useful way we need to
extract both the carve tables (which tell us the item drops) and the
association to specific monsters the game uses.

## Carve Tables

The header pointer for carve tables is located at
`0x00000124` in the G1 `mhfdat.bin`, which points to an array
of carve drop table pointers. The size of this array
and by extension the number of Carve Drop tables is
determined by the [Quantities Pointer]() at Offset TODO.
Each of the pointers in the array in turn points
to a single Drop table.

### Carve Drop Table layout

A Carve Drop Table lists all the item drops for a specific carve
in a sequence until the FF FF terminator. A single Item Drop
entry within a carve table has the following structure.

```c
struct CarveTableItemDrop{
    u16 percantage // the drop chance
    u16 itemId // the item that drops
}

```

## Associating Carve Tables with Monster

For the Carve Table Data to be useful we need to
associate the data with a carve of specific monster of
a specific rank.

A carve can be one of:

- Body Carve
- Tail Carve
- Shiny Drop

A rank can be one of:

- Low Rank (LR)
- High Rank (HR)
- Arena, since these can have different carves
- G-Rank (GR)
