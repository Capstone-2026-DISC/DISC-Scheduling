<div align="center">

<img src="assets/banner.svg" alt="DISC Scheduling" width="100%">

# DISC Scheduling

Plataforma web de apoyo a la programación académica del Departamento de Ingeniería de Sistemas y Computación de la Universidad Católica del Norte

![UCN](https://img.shields.io/badge/Universidad-Cat%C3%B3lica%20del%20Norte-0b2545?style=for-the-badge)
![Capstone](https://img.shields.io/badge/Capstone-2026-13a89e?style=for-the-badge)
![Docker](https://img.shields.io/badge/Docker-listo-2496ED?style=for-the-badge&logo=docker&logoColor=white)
![GitHub Actions](https://img.shields.io/badge/GitHub-Actions-2088FF?style=for-the-badge&logo=githubactions&logoColor=white)
![Idioma](https://img.shields.io/badge/Idioma-Espa%C3%B1ol-c1121f?style=for-the-badge)

</div>

## Sobre el proyecto

Cada semestre el Encargado Docente arma a mano la oferta académica del departamento, asignando asignatura, docente, sala y bloque, y controla por separado el gasto en profesores hora y ayudantes. Este proyecto busca automatizar ese trabajo con una plataforma web que genere horarios sin choques y estime el costo docente de cada semestre.

## Qué incluye

- Módulo base con los datos académicos de cada periodo y contratos de integración para otros módulos
- Módulo de horarios que lleva la planilla y las restricciones a un motor de optimización y valida el resultado
- Módulo financiero que compara el costo de profesores hora y ayudantes con el presupuesto
- Componente predictivo opcional para estimar la inscripción de cada asignatura

## Cómo se construye

- Arquitectura web modular con un adaptador que permite cambiar el motor de horarios
- FET como motor inicial, con alternativas como MiniZinc y Gurobi
- Entregas por iteración publicadas como releases
- Despliegue con contenedores Docker y pruebas automáticas en GitHub Actions

## Equipo

| Integrante | Rol |
| --- | --- |
| Nicolás Álvarez Díaz | Estudiante |
| Fabián Carrasco Pallotti | Estudiante |
| Cristian Jiménez Fuentes | Estudiante |
| Dr. Brian Keith Norambuena | Profesor guía |

Proyecto desarrollado para el Departamento de Ingeniería de Sistemas y Computación de la Universidad Católica del Norte, Antofagasta
