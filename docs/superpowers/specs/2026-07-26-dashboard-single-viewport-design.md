# Dashboard Single-Viewport Design

## Goal

Make the complete desktop ASV dashboard visible in one browser viewport so a camera can record every operational function without vertical page scrolling.

## Scope

- Desktop browser widths above 960 px.
- Keep every remaining panel and control visible: connection state, surface camera, underwater camera, model/telemetry status, navigation map, mission controls, timeline, and channel footer.
- Preserve the existing dark control-room visual language and all current data behavior.
- Mobile and narrow tablet layouts remain vertically scrollable for usability.
- Remove the complete `Course layout / ASV KKI 2026` option panel, including Navigation, Surface imaging, Underwater imaging, and Finish dock controls.
- Remove the `0% proposal route` progress copy and do not display the phrase `proposal route` anywhere in the interface.

## Layout

The desktop shell becomes a fixed-height `100dvh` grid with four areas:

1. A compact full-width connection bar.
2. A main row with the camera/status overview on the left and mission map on the right.
3. A compact full-width mission panel containing summary, controls, and the seven-step timeline.
4. A slim full-width channel footer.

The main row receives the largest flexible height. The mission row receives only the height required for its controls and timeline. All grid children use `min-height: 0` so camera media and the map shrink inside their assigned cells instead of extending the document.

## Panel Behavior

- The page itself uses `overflow: hidden` only on desktop.
- No desktop panel requires internal scrolling for the normal dashboard state.
- Camera media fills the available panel height with `object-fit: contain`; the feed is never cropped.
- The map canvas fills the complete available panel width; the removed course-layout option column does not reserve empty space.
- Repeated spacing, heading margins, panel padding, status rows, mission buttons, and timeline cards become denser on desktop without reducing the base font below readable control-room sizes.
- Alerts occupy a compact overlay/row and must not push the dashboard beyond the viewport.

## Responsive Rules

- `min-width: 60.0625rem`: enforce the single-viewport control-room grid.
- `max-width: 60rem`: retain the existing flowing layout and normal page scrolling.
- Short desktop viewports use a denser variant that reduces gaps, padding, metadata spacing, and mission card height while preserving all controls.
- The layout must fit at both 1920×1080 and the previously audited 1440×1000 desktop viewport.

## Accessibility and Interaction

- Existing semantic regions, headings, mission buttons, focus states, and status text remain unchanged.
- No remaining information is hidden behind tabs, accordions, hover states, or clipped overflow.
- Mission simulation remains explicitly labelled `SIMULATION / DEMO` and `RC MANUAL — no MAVLink commands`.

## Verification

- Existing component and behavior tests remain green.
- Production typecheck and build succeed.
- Browser smoke tests at 1920×1080 and 1440×1000 confirm `document.documentElement.scrollHeight <= window.innerHeight`.
- Visual inspection confirms all remaining major panels, mission controls, seven timeline steps, map, and footer are visible at once; no course-layout option panel or `proposal route` copy remains.
- A narrow mobile smoke test confirms normal vertical scrolling still works and content is not clipped.
