export const handler = async (event, context) => {
    return {
        statusCode: 200,
        headers: {
            'Strict-Transport-Security': 'max-age=31536000; includeSubDomains',
            'Content-Type': 'application/json',
            'X-Content-Type-Options': 'nosniff',
            'X-Frame-Options': 'DENY',
        },
        body: JSON.stringify({
            message: "Hello from the example function!",
        }),
    };
};
