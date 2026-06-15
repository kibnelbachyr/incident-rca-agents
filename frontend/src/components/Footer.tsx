export default function Footer() {
  return (
    <footer className="footer">
      <p className="footer__caption">Built for VivaTech — presented by SoftwareOne</p>
      <div className="footer__brands">
        <a className="brand-badge" href="https://www.softwareone.com/en" target="_blank" rel="noreferrer">
          <span className="brand-badge__mark">S1</span>
          <span className="brand-badge__name">SoftwareOne</span>
        </a>
        <span className="footer__divider" aria-hidden="true" />
        <a className="brand-badge" href="https://vivatech.com/" target="_blank" rel="noreferrer">
          <span className="brand-badge__mark">VT</span>
          <span className="brand-badge__name">VivaTech</span>
        </a>
      </div>
    </footer>
  );
}
