import { Link } from "react-router-dom";

export function NotFound() {
  return (
    <section>
      <h1 className="font-serif text-2xl font-semibold">Page not found</h1>
      <p className="mt-2">
        <Link to="/" className="underline">
          Back to Ask
        </Link>
      </p>
    </section>
  );
}
