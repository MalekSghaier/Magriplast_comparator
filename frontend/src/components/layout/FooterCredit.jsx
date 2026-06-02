export default function FooterCredit({ fixed = false, light = false }) {
  return (
    <footer
      style={{
        position: fixed ? "absolute" : "static",
        left: fixed ? 0 : "auto",
        right: fixed ? 0 : "auto",
        bottom: fixed ? "12px" : "auto",
        padding: fixed ? "0 16px" : "14px 24px 18px",
        textAlign: "center",
        color: light ? "rgba(255,255,255,0.46)" : "#78909c",
        fontSize: "0.72rem",
        fontWeight: 500,
        letterSpacing: "0.02em",
        pointerEvents: "none",
      }}
    >
      Powered By UlyTech (R) 2026
    </footer>
  );
}
