# Aletheia brand & interface system

## The idea: a second pair of eyes

Aletheia is calm, observant and practical. It makes software agents accountable
without presenting itself as another agent or an all-powerful security boundary.
The name is **Aletheia** in prose and **aletheia.** in the wordmark. Aletheia
(αλήθεια, Greek for “truth”) is one word: claims are only real once verified.
Avoid infant/care-service imagery: this is developer tooling.

The original **watchful bracket** mark combines rounded code brackets, two alert
eyes, and a small check-shaped smile. Brackets suggest code and a protective
boundary; the check connects the face directly to verification.

## Assets

- `docs/brand/logo.svg` — primary violet mark, infinitely scalable.
- `docs/brand/logo-monochrome.svg` — single-color dark mark.
- `docs/brand/wordmark.svg` — wordmark for light surfaces.
- `docs/brand/wordmark-dark.svg` — reversed wordmark on charcoal.
- `docs/brand/logo.png` — high-resolution raster mark.
- `docs/brand/readme-banner.svg` — repository cover artwork.
- `docs/brand/social-card.png` — 1200×630 social/repository image.
- `docs/brand/console-desktop.png` — actual browser capture of labeled demo mode.
- `docs/brand/console-mobile.png` — actual narrow-screen browser capture.
- `aletheia/web/assets/oversight.svg` — original in-product workflow illustration.

Keep at least one eye-width of clear space around the mark. Minimum icon size:
24 px; use 32 px or larger in primary navigation. Do not stretch it, rotate it,
put it on noisy imagery, or substitute an unrelated mascot. The interface uses
text labels alongside icons; the logo is not a status indicator.

## Palette

| Role | Value | Use |
| --- | --- | --- |
| Watchful violet | `#8871F6` | Logo and illustration |
| Action violet | `#7654D0` | Primary controls and active accents |
| Night | `#19191F` | Sidebar and dark branding |
| Ink | `#282730` | Primary text |
| Canvas | `#F8F9FB` | Workspace background |
| Soft lavender | `#F1EDFC` | Supporting surfaces |
| Evidence green | `#476F54` | Verified/passed text |
| Recovery amber | `#7A6230` | Recovery status text |
| Failure rose | `#8E545F` | Failed/unverified state text |

Color never carries status alone: use an icon and an explicit label. Pastels
belong on surfaces and illustrations, not low-contrast body text. Keep contrast
checks in the browser test suite when changing theme values.

## Typography and layout

Manrope is self-hosted locally under the SIL Open Font License. No Google Fonts
or tracking request is made at runtime. The UI uses variable font weights,
compact mono type for IDs and evidence, 7–12 px corner radii, fine borders, and
modest shadows. Use a dark navigation rail and a quiet, light work area. Primary
actions use solid violet; destructive-looking actions are deliberately absent
from a read-only product.

On mobile, navigation becomes a menu and metrics use a two-column layout.
Wide evidence tables scroll inside their cards, not the entire page. Dialogs
retain keyboard focus and support Escape. Respect reduced-motion settings.

## Voice

Say **“Verified by configured checks.”** Not “Guaranteed correct.”
Say **“Recorded in progress.”** Not “Agent connected” without a heartbeat.
Say **“Inspect retained changes.”** Not “We saved everything.”
Say **“Recovery budget exhausted.”** Not “Something went wrong.”

Core line: **Your agents build. We check the work.**
Supporting line: **A little oversight. A lot more confidence.**

Demo screenshots must retain their DEMO label. Do not turn illustrative metrics
into measured product results or present a scripted endpoint as a real model.

The original assets are supplied in this repository under the project's Apache
License 2.0 (see `LICENSE`). Font license terms are supplied separately with the
font (SIL Open Font License).
