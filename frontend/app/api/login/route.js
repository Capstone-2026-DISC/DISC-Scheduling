export async function POST(request) {
    const { email, password } = await request.json();
    //check the backend for the user credentials




    if (!email || !password) {
        return new Response(JSON.stringify({ message: "Email and password are required" }), {
            status: 400,
            headers: { "Content-Type": "application/json" },
        });
    }

    //if the credentials are valid, return a success response
    return new Response(JSON.stringify({ message: "Login successful" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
    });
}