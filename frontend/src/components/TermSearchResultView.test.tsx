import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import TermSearchResultView from './TermSearchResultView';
import type { AlternativeResult, SingleMappingResponse } from '../types/mapping';

function bestMatch(overrides: Partial<SingleMappingResponse> = {}): SingleMappingResponse {
  return {
    source_term: 'sbp',
    source_label: 'Systolic blood pressure',
    source_type: 'numeric',
    target_code: 'LOINC:8480-6',
    target_term: 'Systolic blood pressure',
    ontology: 'LOINC',
    confidence: 0.91,
    logic_type: 'rag',
    notes: 'Mapped.',
    alternatives: [],
    configured_provider: 'ollama',
    configured_model: 'llama3.2',
    retrieval_mode: 'public',
    target_url: 'https://loinc.org/8480-6',
    ...overrides,
  };
}

function alternative(overrides: Partial<AlternativeResult> = {}): AlternativeResult {
  return {
    code: 'LOINC:76534-7',
    term: 'Diastolic blood pressure',
    ontology: 'LOINC',
    confidence: 0.55,
    source: 'rag',
    url: 'https://loinc.org/76534-7',
    ...overrides,
  };
}

describe('TermSearchResultView best-match link', () => {
  it('renders the code as an external anchor with the exact href when target_url exists', () => {
    render(<TermSearchResultView bestMatch={bestMatch()} alternatives={[]} />);

    const link = screen.getByRole('link', { name: 'LOINC:8480-6' });
    expect(link).toHaveAttribute('href', 'https://loinc.org/8480-6');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('still renders the term as ordinary text next to the code', () => {
    render(<TermSearchResultView bestMatch={bestMatch()} alternatives={[]} />);

    expect(document.querySelector('.result-code-term')?.textContent).toBe(
      'LOINC:8480-6 · Systolic blood pressure',
    );
  });

  it('renders the code as plain text (not a link) when target_url is null', () => {
    render(
      <TermSearchResultView bestMatch={bestMatch({ target_url: null })} alternatives={[]} />,
    );

    expect(screen.queryByRole('link', { name: 'LOINC:8480-6' })).not.toBeInTheDocument();
    expect(screen.getByText('LOINC:8480-6', { exact: false })).toBeInTheDocument();
    expect(document.querySelector('.result-code-term')?.textContent).toBe(
      'LOINC:8480-6 · Systolic blood pressure',
    );
  });

  it('renders the code as plain text when target_url is undefined', () => {
    render(
      <TermSearchResultView bestMatch={bestMatch({ target_url: undefined })} alternatives={[]} />,
    );

    expect(screen.queryByRole('link', { name: 'LOINC:8480-6' })).not.toBeInTheDocument();
  });

  it('does not render an external link for an UNMAPPED (no-match) result', () => {
    render(
      <TermSearchResultView
        bestMatch={bestMatch({ target_code: 'UNMAPPED', target_term: 'UNMAPPED', ontology: '' })}
        alternatives={[]}
        noMatch
      />,
    );

    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });

  it('copy button label and click handler are unaffected by the link — still the raw CURIE', async () => {
    const user = userEvent.setup();
    const onCopy = vi.fn();

    render(<TermSearchResultView bestMatch={bestMatch()} alternatives={[]} onCopy={onCopy} />);

    const copyButton = screen.getByRole('button', { name: /copy code: loinc:8480-6/i });
    await user.click(copyButton);

    expect(onCopy).toHaveBeenCalledTimes(1);
  });

  it('is keyboard reachable via native anchor semantics', () => {
    render(<TermSearchResultView bestMatch={bestMatch()} alternatives={[]} />);

    const link = screen.getByRole('link', { name: 'LOINC:8480-6' });
    link.focus();
    expect(link).toHaveFocus();
  });
});

describe('TermSearchResultView alternatives links', () => {
  it('gives each alternative its own href', () => {
    const alternatives = [
      alternative({ code: 'LOINC:76534-7', url: 'https://loinc.org/76534-7' }),
      alternative({ code: 'LOINC:76215-3', url: 'https://loinc.org/76215-3' }),
    ];
    render(
      <TermSearchResultView bestMatch={bestMatch()} alternatives={alternatives} onPromote={() => {}} />,
    );

    expect(screen.getByRole('link', { name: 'LOINC:76534-7' })).toHaveAttribute(
      'href',
      'https://loinc.org/76534-7',
    );
    expect(screen.getByRole('link', { name: 'LOINC:76215-3' })).toHaveAttribute(
      'href',
      'https://loinc.org/76215-3',
    );
  });

  it('renders an alternative without a url as plain text', () => {
    render(
      <TermSearchResultView
        bestMatch={bestMatch()}
        alternatives={[alternative({ url: undefined })]}
        onPromote={() => {}}
      />,
    );

    expect(screen.queryByRole('link', { name: 'LOINC:76534-7' })).not.toBeInTheDocument();
    expect(screen.getByText('LOINC:76534-7')).toBeInTheDocument();
  });

  it('clicking an alternative code link opens the external page and does not promote the row', async () => {
    const user = userEvent.setup();
    const onPromote = vi.fn();
    render(
      <TermSearchResultView
        bestMatch={bestMatch()}
        alternatives={[alternative()]}
        onPromote={onPromote}
      />,
    );

    await user.click(screen.getByRole('link', { name: 'LOINC:76534-7' }));

    expect(onPromote).not.toHaveBeenCalled();
  });

  it('clicking elsewhere on the alternative row still promotes it', async () => {
    const user = userEvent.setup();
    const onPromote = vi.fn();
    const alt = alternative();
    render(
      <TermSearchResultView bestMatch={bestMatch()} alternatives={[alt]} onPromote={onPromote} />,
    );

    await user.click(screen.getByText(alt.term));

    expect(onPromote).toHaveBeenCalledWith(alt);
  });

  it('keyboard activation (Enter on the row) still promotes the alternative', async () => {
    const user = userEvent.setup();
    const onPromote = vi.fn();
    const alt = alternative();
    render(
      <TermSearchResultView bestMatch={bestMatch()} alternatives={[alt]} onPromote={onPromote} />,
    );

    const row = screen.getByRole('button', { name: `Promote ${alt.code} to best match` });
    row.focus();
    await user.keyboard('{Enter}');

    expect(onPromote).toHaveBeenCalledWith(alt);
  });

  it('clicking the info/details tooltip trigger on an alternative does not promote the row', async () => {
    const user = userEvent.setup();
    const onPromote = vi.fn();
    const alt = alternative({ explanation: 'Related vital sign.' });
    render(
      <TermSearchResultView bestMatch={bestMatch()} alternatives={[alt]} onPromote={onPromote} />,
    );

    await user.click(
      screen.getByRole('button', { name: new RegExp(`mapping details for ${alt.code}`, 'i') }),
    );

    expect(onPromote).not.toHaveBeenCalled();
  });
});
