import { useState } from 'react';

interface AccordionSectionProps {
  title: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}

export default function AccordionSection({ title, defaultOpen = true, children }: AccordionSectionProps) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="accordion">
      <button className="accordion-header" onClick={() => setOpen((o) => !o)} type="button">
        <span className="accordion-title">{title}</span>
        <span className={`accordion-chevron ${open ? 'accordion-chevron-open' : ''}`}>▾</span>
      </button>
      {open && <div className="accordion-body">{children}</div>}
    </div>
  );
}
