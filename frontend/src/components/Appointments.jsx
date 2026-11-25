/**
 * Appointments ledger – booked and cancelled appointments.
 *
 * Props:
 *   appointments – array from /api/appointments
 *   loading      – boolean
 */
export default function Appointments({ appointments = [], loading = false }) {
  if (loading) {
    return (
      <div className="appointments-panel">
        <h2 className="section-heading">Appointment Ledger</h2>
        <p className="appointments-loading">Loading appointments…</p>
      </div>
    );
  }

  return (
    <div className="appointments-panel">
      <h2 className="section-heading">Appointment Ledger</h2>

      {appointments.length === 0 ? (
        <p className="appointments-empty">
          No appointments yet. Book one through the voice assistant.
        </p>
      ) : (
        <div className="appointments-list">
          {appointments.map((appt) => (
            <div
              key={appt.id}
              className={`appointment-row appt-${appt.status}`}
            >
              <div className="appt-id">#{appt.id}</div>
              <div className="appt-details">
                <span className="appt-doctor">{appt.doctor_name}</span>
                <span className="appt-specialty">{appt.specialty}</span>
                <span className="appt-datetime">
                  {appt.slot_date} at {appt.slot_time}
                </span>
              </div>
              <div className="appt-patient">
                <span className="appt-patient-name">{appt.patient_name}</span>
                <span className="appt-patient-phone">{appt.patient_phone}</span>
              </div>
              <div className={`appt-status-badge status-${appt.status}`}>
                {appt.status}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
