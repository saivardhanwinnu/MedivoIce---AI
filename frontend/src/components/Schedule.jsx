import { useState, useMemo } from "react";

/**
 * Doctors and available slots displayed as a clinical timeline.
 *
 * Props:
 *   doctors – array from /api/doctors (each has .slots array)
 *   loading – boolean
 */
export default function Schedule({ doctors = [], loading = false }) {
  const [activeSpecialty, setActiveSpecialty] = useState("All");

  const specialties = useMemo(() => {
    const set = new Set(doctors.map((d) => d.specialty));
    return ["All", ...Array.from(set).sort()];
  }, [doctors]);

  const filtered = useMemo(() => {
    if (activeSpecialty === "All") return doctors;
    return doctors.filter((d) => d.specialty === activeSpecialty);
  }, [doctors, activeSpecialty]);

  if (loading) {
    return (
      <div className="schedule-panel">
        <h2 className="section-heading">Physician Schedule</h2>
        <p className="schedule-loading">Loading schedule…</p>
      </div>
    );
  }

  return (
    <div className="schedule-panel">
      <h2 className="section-heading">Physician Schedule</h2>

      <div className="specialty-tabs">
        {specialties.map((s) => (
          <button
            key={s}
            className={`tab-btn ${activeSpecialty === s ? "tab-active" : ""}`}
            onClick={() => setActiveSpecialty(s)}
          >
            {s}
          </button>
        ))}
      </div>

      <div className="schedule-list">
        {filtered.map((doc) => (
          <div key={doc.id} className="doctor-row">
            <div className="doctor-info">
              <span className="doctor-name">{doc.name}</span>
              <span className="doctor-specialty">{doc.specialty}</span>
            </div>

            <div className="slots-grid">
              {doc.slots && doc.slots.length > 0 ? (
                doc.slots.map((slot) => (
                  <div
                    key={slot.slot_id}
                    className={`slot-chip ${slot.is_booked ? "slot-booked" : "slot-open"}`}
                    title={`${slot.slot_date} ${slot.slot_time} — ${slot.is_booked ? "Booked" : "Available"}`}
                  >
                    <span className="slot-date">{slot.slot_date}</span>
                    <span className="slot-time">{slot.slot_time}</span>
                  </div>
                ))
              ) : (
                <span className="no-slots">No slots</span>
              )}
            </div>

            <div className="available-count">
              {doc.available_slots_count} open
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
