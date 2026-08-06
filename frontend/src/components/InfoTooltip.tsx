import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

interface Props {
  label: string;
  tooltip: ReactNode;
  bubbleClassName?: string;
}

export default function InfoTooltip({ label, tooltip, bubbleClassName }: Props) {
  const tooltipId = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const bubbleRef = useRef<HTMLSpanElement>(null);
  const [visible, setVisible] = useState(false);
  const [pinned, setPinned] = useState(false);
  const [position, setPosition] = useState({ top: 0, left: 0 });

  function updatePosition() {
    const trigger = triggerRef.current;
    if (!trigger) return;
    const rect = trigger.getBoundingClientRect();
    setPosition({
      top: rect.top - 6,
      left: rect.left + rect.width / 2,
    });
  }

  function showTooltip() {
    updatePosition();
    setVisible(true);
  }

  function hideTooltip() {
    if (pinned) return;
    setVisible(false);
  }

  useEffect(() => {
    if (!visible) return undefined;

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setPinned(false);
        setVisible(false);
        triggerRef.current?.focus();
      }
    }

    function handlePointerDown(event: PointerEvent) {
      const target = event.target as Node | null;
      if (
        target
        && (triggerRef.current?.contains(target) || bubbleRef.current?.contains(target))
      ) {
        return;
      }
      setPinned(false);
      setVisible(false);
    }

    function handleViewportChange() {
      updatePosition();
    }

    document.addEventListener('keydown', handleKeyDown);
    document.addEventListener('pointerdown', handlePointerDown);
    window.addEventListener('scroll', handleViewportChange, true);
    window.addEventListener('resize', handleViewportChange);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.removeEventListener('pointerdown', handlePointerDown);
      window.removeEventListener('scroll', handleViewportChange, true);
      window.removeEventListener('resize', handleViewportChange);
    };
  }, [visible]);

  const bubble = (
    <span
      ref={bubbleRef}
      id={tooltipId}
      className={[
        'info-tooltip-bubble',
        visible ? 'info-tooltip-bubble--visible' : '',
        bubbleClassName ?? '',
      ].filter(Boolean).join(' ')}
      role="tooltip"
      style={{
        top: position.top,
        left: position.left,
      }}
    >
      {tooltip}
    </span>
  );

  return (
    <span className="info-tooltip">
      <button
        ref={triggerRef}
        type="button"
        className="info-tooltip-trigger"
        aria-label={label}
        aria-describedby={tooltipId}
        aria-expanded={visible}
        onMouseEnter={showTooltip}
        onMouseLeave={hideTooltip}
        onFocus={showTooltip}
        onBlur={hideTooltip}
        onClick={() => {
          updatePosition();
          setPinned((current) => {
            const next = !current;
            setVisible(next || !visible);
            return next;
          });
        }}
      >
        <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
          <circle cx="12" cy="12" r="9" />
          <path d="M12 10.75V16" />
          <path d="M12 8h.01" />
        </svg>
      </button>
      {createPortal(bubble, document.body)}
    </span>
  );
}
