export function OperationalShell({ currentSection, sections = [], healthStrip, children }) {
  return (
    <section className="operational-shell">
      <aside className="card operational-shell-nav-card">
        <nav className="operational-shell-nav" aria-label="Operational sections">
          {sections.map((section) => (
            <button
              key={section.id}
              type="button"
              className={`btn operational-nav-btn ${currentSection === section.id ? "btn-primary" : ""}`}
              onClick={section.onClick}
            >
              {section.label}
            </button>
          ))}
        </nav>
      </aside>
      <div className="operational-shell-content">
        {healthStrip}
        {children}
      </div>
    </section>
  );
}
