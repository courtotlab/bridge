import type { MappingDetailsInput } from '../utils/mappingDetails';
import { getMappingDetailSections, hasMappingDetails } from '../utils/mappingDetails';
import InfoTooltip from './InfoTooltip';

interface MappingDetailsContentProps {
  details: MappingDetailsInput;
  explanationLabel?: string;
}

export function MappingDetailsContent({ details, explanationLabel }: MappingDetailsContentProps) {
  const sections = getMappingDetailSections(details, explanationLabel);
  if (sections.length === 0) return null;

  return (
    <span className="mapping-details-tooltip-content">
      {sections.map((section) => (
        <span key={section.label} className="mapping-details-tooltip-section">
          <span className="mapping-details-tooltip-label">{section.label}</span>
          <span className="mapping-details-tooltip-value">{section.value}</span>
        </span>
      ))}
    </span>
  );
}

interface MappingDetailsTooltipProps {
  code: string;
  details: MappingDetailsInput;
  explanationLabel?: string;
}

export default function MappingDetailsTooltip({ code, details, explanationLabel }: MappingDetailsTooltipProps) {
  if (!hasMappingDetails(details)) return null;

  return (
    <InfoTooltip
      label={`View mapping details for ${code}`}
      bubbleClassName="mapping-details-tooltip"
      tooltip={<MappingDetailsContent details={details} explanationLabel={explanationLabel} />}
    />
  );
}
