import "../styles/globals.css";

export const metadata = {
  title: "DISC Scheduling",
  description: "Programación académica y costo docente para el DISC",
};

export default function RootLayout({ children }) {
  return (
    <html lang="es">
      <body>{children}</body>
    </html>
  );
}
