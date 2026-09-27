import Link from "next/link";

export default function NotFound() {
  return (
    <div className="center-screen">
      <div className="empty-state">
        <h3>Not found</h3>
        <p>This page doesn’t exist.</p>
        <Link href="/" className="btn" style={{ marginTop: 12 }}>Back to projects</Link>
      </div>
    </div>
  );
}
