addEventListener('fetch', event => {
    event.respondWith(handleRequest(event.request));
});

async function handleRequest(request) {
    if (request.method === 'POST') {
        const formData = await request.formData();
        const imageFile = formData.get('image_file');
        if (!imageFile) {
            return new Response('No file uploaded', { status: 400 });
        }

        // You can use fetch to call your Flask server here
        const response = await fetch('https://your-flask-app-url/upload', {
            method: 'POST',
            body: formData,
        });

        return response; // Forward the response from Flask
    } else {
        return new Response('Only POST requests are supported', { status: 405 });
    }
}
