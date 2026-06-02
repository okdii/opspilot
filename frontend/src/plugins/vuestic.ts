import { createVuestic } from 'vuestic-ui'

// Single source of color truth for Vuestic components.
// These hex values MUST stay in lockstep with the CSS custom properties in
// App.vue (:root). Changing a brand color means editing BOTH places.
export const vuestic = createVuestic({
  config: {
    colors: {
      currentPresetName: 'dark',
      variables: {
        primary: '#6366f1',          // --accent
        secondary: '#818cf8',        // --accent-2
        success: '#22c55e',          // --green
        warning: '#f59e0b',          // --amber
        danger: '#ef4444',           // --red
        info: '#3b82f6',             // --blue
        backgroundPrimary: '#0f1117', // --bg
        backgroundSecondary: '#1a1d27', // --surface
        backgroundElement: '#22263a', // --surface-2
        backgroundBorder: '#2e3354',  // --border
        textPrimary: '#e2e8f0',       // --text
        textInverted: '#0f1117',
      },
    },
  },
})
