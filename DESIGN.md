---
version: alpha
name: Codex Mem Dashboard
description: Dense local productivity UI for project-scoped Codex memory, file selection, and compact chat context bundles.
colors:
  primary: "#2563EB"
  primary-strong: "#1E40AF"
  on-primary: "#FFFFFF"
  accent: "#D97706"
  accent-soft: "#FFF7ED"
  background: "#F8FAFC"
  surface: "#FFFFFF"
  surface-muted: "#F1F5F9"
  text: "#0F172A"
  muted: "#475569"
  muted-2: "#64748B"
  border: "#D7E0EA"
  border-strong: "#A9B8CA"
  success: "#047857"
  danger: "#DC2626"
typography:
  title:
    fontFamily: Fira Sans
    fontSize: 1.5rem
    fontWeight: 700
    lineHeight: 1.25
    letterSpacing: 0
  body:
    fontFamily: Fira Sans
    fontSize: 1rem
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: 0
  label:
    fontFamily: Fira Sans
    fontSize: 0.875rem
    fontWeight: 600
    lineHeight: 1.35
    letterSpacing: 0
  mono:
    fontFamily: Fira Code
    fontSize: 0.8125rem
    fontWeight: 500
    lineHeight: 1.55
    letterSpacing: 0
rounded:
  sm: 4px
  md: 8px
spacing:
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
components:
  app-background:
    backgroundColor: "{colors.background}"
    textColor: "{colors.text}"
  panel:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.md}"
    padding: 16px
  panel-muted:
    backgroundColor: "{colors.surface-muted}"
    textColor: "{colors.muted}"
    rounded: "{rounded.md}"
    padding: 16px
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    rounded: "{rounded.sm}"
    height: 44px
    padding: 14px
  button-primary-hover:
    backgroundColor: "{colors.primary-strong}"
    textColor: "{colors.on-primary}"
    rounded: "{rounded.sm}"
    height: 44px
    padding: 14px
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.sm}"
    height: 44px
    padding: 14px
  button-tertiary:
    backgroundColor: "{colors.accent-soft}"
    textColor: "{colors.text}"
    rounded: "{rounded.sm}"
    height: 44px
    padding: 14px
  accent-swatch:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.text}"
    rounded: "{rounded.sm}"
    padding: 8px
  metadata-chip:
    backgroundColor: "{colors.surface-muted}"
    textColor: "{colors.muted}"
    rounded: "{rounded.sm}"
    padding: 8px
  subtle-label:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.muted-2}"
    padding: 8px
  divider:
    backgroundColor: "{colors.border}"
    textColor: "{colors.text}"
    height: 1px
  active-divider:
    backgroundColor: "{colors.border-strong}"
    textColor: "{colors.text}"
    height: 1px
  success-chip:
    backgroundColor: "{colors.success}"
    textColor: "{colors.on-primary}"
    rounded: "{rounded.sm}"
    padding: 8px
  danger-chip:
    backgroundColor: "{colors.danger}"
    textColor: "{colors.on-primary}"
    rounded: "{rounded.sm}"
    padding: 8px
  selection-active:
    backgroundColor: "#EFF6FF"
    textColor: "{colors.text}"
    rounded: "{rounded.md}"
---

## Overview

The dashboard is a compact operational tool. It should prioritize scanning, filtering, selecting, and copying project context over presentation copy or decorative composition.

## Colors

The base is a neutral slate workspace with blue for primary action and amber for secondary emphasis. Surfaces stay white or near-white so memory rows, file paths, and transcript text remain readable.

## Typography

Fira Sans carries the interface because it is compact and readable. Fira Code is reserved for paths, counts, commands, and transcript excerpts.

## Layout

Use a persistent left scope rail, a central memory/results column, and a right context panel. Keep panels dense, with 8px radii, 16px panel padding, and stable row dimensions.

## Elevation & Depth

Use borders first and soft shadows only on hover or active rows. Avoid floating decorative sections.

## Shapes

Use 4px radius for controls and 8px radius for framed tools, rows, and panels.

## Components

Primary buttons trigger context-building actions. Segmented controls switch search and file modes. Checkboxes are the selection primitive for sessions and files.

## Do's and Don'ts

Do keep copied context bundles short: summaries, decisions, session IDs, and selected file paths only. Do show missing local files clearly. Do not render a landing hero, decorative gradients, or long instructional text inside the app.
