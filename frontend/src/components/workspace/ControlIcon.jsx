import React from "react";

// Preserve the exact Figma geometry. System-color masking keeps fixed-color SVG
// glyphs visible in either forced-colors palette without inventing another icon.
export default function ControlIcon({ asset }) {
  return <><img src={asset} alt="" /><span className="icon-contrast" aria-hidden="true"
    style={{ maskImage: `url("${asset}")` }} /></>;
}
