import { useState, useEffect, useCallback } from "react";

/**
 * Custom hook to fetch data from the FastAPI backend.
 * Returns { doctors, appointments, loading, error, refetch }.
 */
export function useApi() {
  const [doctors, setDoctors] = useState([]);
  const [appointments, setAppointments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchAll = useCallback(async () => {
    try {
      setError(null);
      const [docRes, apptRes] = await Promise.all([
        fetch("/api/doctors"),
        fetch("/api/appointments"),
      ]);

      if (!docRes.ok) throw new Error(`Doctors API: ${docRes.status}`);
      if (!apptRes.ok) throw new Error(`Appointments API: ${apptRes.status}`);

      const docData = await docRes.json();
      const apptData = await apptRes.json();

      setDoctors(docData.doctors || []);
      setAppointments(apptData.appointments || []);
    } catch (err) {
      setError(err.message);
      console.error("API fetch error:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  return { doctors, appointments, loading, error, refetch: fetchAll };
}
