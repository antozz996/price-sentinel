import { ChevronLeft, ChevronRight } from 'lucide-react';

interface PaginationProps {
  limit: number;
  offset: number;
  total: number;
  onChange: (limit: number, offset: number) => void;
}

export default function Pagination({ limit, offset, total, onChange }: PaginationProps) {
  const currentPage = Math.floor(offset / limit) + 1;
  const totalPages = Math.max(1, Math.ceil(total / limit));
  const startItem = total === 0 ? 0 : offset + 1;
  const endItem = Math.min(total, offset + limit);

  const handlePrev = () => {
    if (currentPage > 1) {
      onChange(limit, (currentPage - 2) * limit);
    }
  };

  const handleNext = () => {
    if (currentPage < totalPages) {
      onChange(limit, currentPage * limit);
    }
  };

  const handleLimitChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const newLimit = parseInt(e.target.value, 10);
    onChange(newLimit, 0); // Reset to page 1 on limit change
  };

  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      marginTop: '24px',
      paddingTop: '20px',
      borderTop: '1px solid var(--border-glass)',
      flexWrap: 'wrap',
      gap: '16px',
      fontSize: '0.85rem',
      color: 'var(--text-secondary)'
    }}>
      {/* Page Size Selector */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <span>Mostra</span>
        <select
          value={limit}
          onChange={handleLimitChange}
          style={{
            background: 'var(--bg-secondary)',
            border: '1px solid var(--border-glass)',
            borderRadius: 'var(--border-radius-sm)',
            color: 'white',
            padding: '6px 12px',
            outline: 'none',
            fontSize: '0.85rem',
            cursor: 'pointer'
          }}
        >
          <option value={10}>10</option>
          <option value={25}>25</option>
          <option value={50}>50</option>
          <option value={100}>100</option>
        </select>
        <span>voci</span>
      </div>

      {/* Page Controls */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
        <button
          className="btn"
          onClick={handlePrev}
          disabled={currentPage === 1}
          style={{
            padding: '8px 12px',
            opacity: currentPage === 1 ? 0.4 : 1,
            cursor: currentPage === 1 ? 'not-allowed' : 'pointer',
            minWidth: '40px',
            justifyContent: 'center'
          }}
        >
          <ChevronLeft size={16} />
        </button>

        <span style={{ fontWeight: 500, color: 'var(--text-primary)' }}>
          Pagina {currentPage} di {totalPages}
        </span>

        <button
          className="btn"
          onClick={handleNext}
          disabled={currentPage === totalPages}
          style={{
            padding: '8px 12px',
            opacity: currentPage === totalPages ? 0.4 : 1,
            cursor: currentPage === totalPages ? 'not-allowed' : 'pointer',
            minWidth: '40px',
            justifyContent: 'center'
          }}
        >
          <ChevronRight size={16} />
        </button>
      </div>

      {/* Info Stats */}
      <div style={{ fontWeight: 500 }}>
        Visualizzate <span style={{ color: 'var(--text-primary)' }}>{startItem}-{endItem}</span> di <span style={{ color: 'var(--text-primary)' }}>{total}</span> voci
      </div>
    </div>
  );
}
