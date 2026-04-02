---
layout: "../../layouts/DocsLayout.astro"
title: "Introduction to the docs for the forward fivers wiki"
author: "Nils Imdahl"
---

# Introduction

These docs aim to explain the data extraction and processes used to
create this wiki and in the process document the structure of
a lot of important data files for Monster Hunter Frontier G1, though a
lot of the info should apply to ZZ as well.

## Client Side Files

There are only a few relevant client site binary files in G1.
Currently this wiki makes use of only two: `mhfdat.bin` and `mhfinf.bin`.

> **Note**:
> To deal with any files in frontier including these once you will first have to
> decrypt and decompress them, often called unpacking. I recommend using [rs-frontier](https://github.com/Paxlord/Rsfrontier#)
> for this. All info on binary formats across these docs only applies to unpacked
> files.

### mfdat.bin

This file contains most of the wiki relevant data, including:

- [Partbreak Tables]()
- [Carve Tables]()
- [Equipment Data]()
- [Weapon Data]()
- [Item Data]()

### mhfinf.bin

This file documents quest metadata such as questIDs, rank, main objectives,
zenny rewards etc. The actual quest files however, live on the server. For
an older Server like G1 some quest files may not be publicly available. For
servers of newer game versions they can be found on the Erupe github or discord.

## Server Side Data

### Quest Files

As previously mentioned all quest files and event files live on the server.
These are individual files for each quest labeled as <quest_id>(d|n)(0|1|2|3).
d=day, n=night and 0=spring 1=summer 2=winter. Details on the quest file format
itself can be found [here]().

### Shop Data

Data for the various in game shops, such as item ids, their cost and purchasing
constraints lives in the shop_items table on the Erupe server.
