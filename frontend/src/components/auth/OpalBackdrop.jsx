import React from "react";
import speck0 from "../../assets/opal/auth/speck-0.svg";
import speck1 from "../../assets/opal/auth/speck-1.svg";
import speck2 from "../../assets/opal/auth/speck-2.svg";
import speck3 from "../../assets/opal/auth/speck-3.svg";
import speck4 from "../../assets/opal/auth/speck-4.svg";
import speck5 from "../../assets/opal/auth/speck-5.svg";
import speck6 from "../../assets/opal/auth/speck-6.svg";
const assets = [speck0, speck1, speck2, speck3, speck4, speck5, speck6];
// Approved Figma positions expressed relative to its 1440 × 900 canvas.
const specks = [[55,73,0],[252,212,1],[449,351,1],[646,490,2],[843,629,1],[1040,768,1],[18,170,3],[215,309,1],[412,448,2],[609,587,1],[806,726,4],[1003,865,2],[1200,128,1],[1397,267,3],[178,406,2],[375,545,1],[572,684,1],[769,823,2],[966,86,1],[1163,225,1],[1360,364,5],[141,503,4],[338,642,1],[535,781,2],[732,44,1],[929,183,1],[1126,322,2],[1323,461,3],[104,600,1],[301,739,2],[498,878,1],[695,141,1],[892,280,6],[1089,419,1],[1286,558,3],[67,697,2],[264,836,1],[461,99,1],[658,238,2],[855,377,1],[1052,516,1],[1249,655,5],[30,794,1],[227,57,4],[424,196,2],[621,335,1],[818,474,1],[1015,613,2],[1212,752,3],[1409,15,1],[190,154,2],[387,293,1],[584,432,1],[781,571,2],[978,710,4],[1175,849,3],[1372,112,2],[153,251,1],[350,390,1],[547,529,2],[744,668,1],[941,807,1],[1138,70,5]];
export default function OpalBackdrop() {
  return <div className="opal-backdrop" aria-hidden="true">{specks.map(([x,y,asset], index) => <img key={index} src={assets[asset]} alt="" draggable="false" style={{ left: `${x / 14.4}%`, top: `${y / 9}%` }} />)}</div>;
}
