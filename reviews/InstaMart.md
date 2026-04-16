# InstaMart

**Repo:** https://github.com/Sujal-cloud/gigshield  
**Confidence:** HIGH  
**Review Date:** 2026-04-16

---

## Tech Stack
- Node.js (commonjs)
- Express.js (^5.2.1)
- Mongoose (^9.3.3)
- Firebase Admin SDK (^13.7.0)
- Socket.io (^4.8.3)
- Axios (^1.14.0)
- Bcrypt.js (^3.0.3)
- CORS (^2.8.6)
- JSON Web Token (^9.0.3)
- dotenv (^17.3.1)
- React (^19.2.4)
- React DOM (^19.2.4)
- React Router DOM (^7.13.2)
- Recharts (^3.8.1)
- Framer Motion (^12.38.0)
- Lucide React (^1.7.0)
- Firebase (^12.11.0)
- Vite (^8.0.1)
- ESLint (^9.39.4)
- Tailwind CSS (^3.4.19)
- PostCSS (^8.5.8)
- Autoprefixer (^10.4.27)
- @vitejs/plugin-react (^6.0.1)
- @types/react (^19.2.14)
- @types/react-dom (^19.2.3)

## Architecture Overview
The InstaMart application is structured with a clear separation between the frontend and backend. The backend, built using Node.js and Express.js, handles authentication, claim processing, dashboard data retrieval, notifications, and real-time communication via Socket.io. It connects to MongoDB Atlas for database operations and integrates with external APIs like OpenWeatherMap, AQICN, and NewsAPI for fetching weather, air quality index, and civic disruption data respectively. The frontend is a React application built with Vite, Tailwind CSS, and Framer Motion for animations. It communicates with the backend via Axios and manages state using Context API.

## Core Features Implemented
- **Authentication:** Users can log in using OTP verification.
- **Claim Processing:** Users can create claims, which are validated and processed based on risk calculations.
- **Dashboard:** Provides real-time data including weather, risk scores, and notifications.
- **Notifications:** In-app and real-time notifications for users.
- **Policy Management:** Allows users to buy and manage insurance policies.
- **Simulation:** Simulates risk scenarios with interactive elements.

## Data Models
- **Claim**
  - user (ObjectId)
  - policy (ObjectId)
  - amount (Number)
  - reason (String)
  - status (String)

- **History**
  - user (ObjectId)
  - action (String)
  - details (String)

- **Notification**
  - user (ObjectId)
  - message (String)
  - read (Boolean)
  - type (String)

- **Policy**
  - user (ObjectId)
  - policyNumber (String)
  - type (String)
  - basePrice (Number)
  - riskScore (Number)
  - premium (Number)
  - coverage (Number)
  - status (String)

- **User**
  - name (String)
  - phone (String)
  - email (String)
  - role (String)
  - policies (Array of ObjectId)

## API Surface
- **POST /auth/sendOTP** → Sends an OTP to a user's phone number.
- **POST /auth/verifyOTP** → Verifies the OTP provided by the user and generates a JWT token.
- **POST /claim/createClaim** → Processes a claim, creates a notification, and sends real-time notifications.
- **GET /claim/getClaims** → Retrieves claims for the authenticated user, including creating a daily risk coverage claim if none exists.
- **PUT /claim/updateStatus** → Updates the status of a specific claim.
- **GET /dashboard/getDashboard** → Retrieves dashboard data for the authenticated user.
- **GET /dashboard/getRiskData** → Fetches risk data based on latitude and longitude, including weather and AQI information.
- **GET /dashboard/getStats** → Retrieves statistics for the authenticated user's policies and claims.
- **GET /dashboard/getWeather** → Fetches current weather data based on latitude and longitude.
- **GET /notification/getNotifications** → Retrieves notifications for the authenticated user.
- **POST /notification/sendNotification** → Sends a notification to the authenticated user.

## Guidewire Integration
NOT FOUND

## External Integrations
- MongoDB Atlas → Database service connected via Mongoose.
- OpenWeatherMap API → Weather data provider referenced in multiple controllers and routes.
- AQICN API → Air quality index data provider referenced in the getRiskData controller.
- NewsAPI (mock fallback) → Civic disruption detection.
- Razorpay Test Mode → Payment processing.
- Render (frontend + backend) → Hosting platform.

## Notable Technical Choices
- **Use of Vite:** As a build tool for the frontend, providing fast development server and optimized builds.
- **Framer Motion:** For animations across multiple components, adding interactive and dynamic UI elements.
- **Custom OTP Store:** Managing OTPs without relying on external services by using a custom store (`otpStore`) and request time tracking (`otpRequestTime`).
- **Separation of Concerns:** Clear separation between backend controllers for specific operations like authentication, claims, dashboard data, notifications, etc.

## Completeness Assessment
**Level:** High  
**Reasoning:** The code provides detailed configurations and implementations for both backend and frontend components, indicating a well-structured project setup with clear purposes and functions. It includes essential integrations with Firebase and Socket.io, as well as comprehensive external API integrations.

## What Is Missing or Incomplete
- **Stubbed Features:** Some features like payment processing might be in stubbed form.
- **TODO Comments:** There are no explicit TODO comments found in the provided summaries.
- **Missing Endpoints:** No specific endpoints or service methods are mentioned as missing.

## Replication Notes
To build a replica of the InstaMart application, you would need:
1. **Backend Setup:**
   - Node.js and Express.js for server setup.
   - Mongoose for MongoDB interactions.
   - Firebase Admin SDK for backend operations.
   - Socket.io for real-time communication.
   - Axios for HTTP requests.
   - Bcrypt.js for password hashing.
   - CORS for handling cross-origin requests.
   - JSON Web Token for authentication.
   - dotenv for environment variables.

2. **Frontend Setup:**
   - React and ReactDOM for building the user interface.
   - Vite as a build tool.
   - Tailwind CSS for styling.
   - PostCSS with Autoprefixer for CSS processing.
   - Framer Motion for animations.
   - ESLint for linting JavaScript and JSX files.

3. **External Integrations:**
   - MongoDB Atlas for database storage.
   - OpenWeatherMap API for weather data.
   - AQICN API for air quality index data.
   - NewsAPI (mock fallback) for civic disruption detection.
   - Razorpay Test Mode for payment processing.
   - Render for hosting the application.

4. **Data Models:**
   - Define and implement models for Claim, History, Notification, Policy, and User as described in the Data Models section.

5. **API Endpoints:**
   - Implement API endpoints as listed in the API Surface section.

6. **Real-time Communication:**
   - Set up Socket.io for real-time notifications and updates.

7. **Authentication:**
   - Implement OTP-based authentication using Firebase Admin SDK or similar services.

8. **Claim Processing:**
   - Develop logic for claim validation, risk calculation, and notification creation.

9. **Dashboard and Notifications:**
   - Integrate with external APIs to fetch real-time data and display it in the dashboard.
   - Implement notification systems for both in-app and real-time alerts.

10. **Policy Management:**
    - Allow users to buy and manage insurance policies with risk assessments.

By following these steps, you should be able to replicate the core functionality of the InstaMart application.